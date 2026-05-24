#!/bin/bash
# wisd installer for Debian/Ubuntu x86_64 VPS.
#
# Installs:
#   - xray (latest stable, /usr/local/bin/xray)
#   - nginx + fcgiwrap (for serving the panel and bash CGI)
#   - systemd unit wisd-xray.service
#   - /var/www/wisd  -- the panel
#   - /var/lib/wisd  -- runtime state (subscriptions, configs, logs)
#   - /etc/sudoers.d/wisd-cgi  -- so www-data can systemctl wisd-xray
#
# Idempotent: safe to run multiple times.
#
# Usage:  sudo bash deploy/install.sh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Run as root: sudo bash $0"; exit 1
fi

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
WEB_ROOT=/var/www/wisd
STATE_DIR=/var/lib/wisd
LOG_DIR=/var/log/wisd
CONF_DIR=/etc/wisd
XRAY_BIN=/usr/local/bin/xray

XRAY_VERSION=${XRAY_VERSION:-1.8.24}

step() { printf '\n=== %s ===\n' "$*"; }

step "Install OS packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
    nginx fcgiwrap jq curl ca-certificates unzip uuid-runtime python3 xxd sudo \
    openssl nftables certbot
# Make sure /etc/sudoers.d exists (minimal Debian images may omit it).
mkdir -p /etc/sudoers.d
chmod 0750 /etc/sudoers.d
grep -q '^@includedir /etc/sudoers.d' /etc/sudoers 2>/dev/null \
    || echo '@includedir /etc/sudoers.d' >> /etc/sudoers

step "Create wisd user and directories"
id -u wisd >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin wisd
mkdir -p "$WEB_ROOT" "$STATE_DIR/subscriptions" "$LOG_DIR" "$CONF_DIR"
chown -R wisd:wisd "$STATE_DIR" "$LOG_DIR"
chmod 0755 "$STATE_DIR" "$LOG_DIR" "$CONF_DIR"

# Make the state dir writable by both wisd (xray) and www-data (CGI).
groupadd -f wisd-rw 2>/dev/null || true
usermod -aG wisd www-data 2>/dev/null || true
chmod 0775 "$STATE_DIR" "$STATE_DIR/subscriptions" "$LOG_DIR"

step "Install Xray $XRAY_VERSION"
if [[ ! -x "$XRAY_BIN" ]] || ! "$XRAY_BIN" version 2>/dev/null | grep -q "$XRAY_VERSION"; then
    tmp=$(mktemp -d)
    arch=$(uname -m)
    case "$arch" in
        x86_64|amd64) zip="Xray-linux-64.zip" ;;
        aarch64|arm64) zip="Xray-linux-arm64-v8a.zip" ;;
        *) echo "Unsupported arch: $arch"; exit 1 ;;
    esac
    url="https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/${zip}"
    echo "Downloading $url"
    curl -fsSL -o "$tmp/xray.zip" "$url"
    unzip -o "$tmp/xray.zip" -d "$tmp" >/dev/null
    install -m 0755 "$tmp/xray" "$XRAY_BIN"
    install -m 0644 "$tmp/geoip.dat" /usr/local/share/xray/geoip.dat 2>/dev/null \
        || (mkdir -p /usr/local/share/xray && install -m 0644 "$tmp/geoip.dat" /usr/local/share/xray/geoip.dat)
    install -m 0644 "$tmp/geosite.dat" /usr/local/share/xray/geosite.dat
    rm -rf "$tmp"
fi

step "Generate VLESS-Reality server keys + proxy credentials"
SERVER_FILE=$STATE_DIR/server.json
if [[ ! -s "$SERVER_FILE" ]]; then
    keys=$("$XRAY_BIN" x25519)
    priv=$(awk -F': ' '/Private/ {print $2}' <<<"$keys" | tr -d '\r ')
    pub=$(awk -F': ' '/Public/ {print $2}' <<<"$keys" | tr -d '\r ')
    short_id=$(head -c 4 /dev/urandom | xxd -p -c 8)
    uuid=$("$XRAY_BIN" uuid 2>/dev/null || cat /proc/sys/kernel/random/uuid)
    pubip=$(curl -s --max-time 4 https://ifconfig.io 2>/dev/null \
            || ip -4 -o addr show scope global | awk '{print $4}' | head -1 | cut -d/ -f1)
    server_name=${WISD_SNI:-www.cloudflare.com}
    proxy_user=wisd_$(head -c 4 /dev/urandom | xxd -p -c 8)
    proxy_pass=$(head -c 18 /dev/urandom | base64 | tr -d '+/=' | head -c 24)
    jq -n --arg uuid "$uuid" \
          --arg pub "$pub" \
          --arg priv "$priv" \
          --arg sid "$short_id" \
          --arg sni "$server_name" \
          --arg host "$pubip" \
          --argjson port "${WISD_VLESS_PORT:-2053}" \
          --arg flow "xtls-rprx-vision" \
          --arg pu "$proxy_user" \
          --arg pp "$proxy_pass" \
          --argjson sp 1080 \
          --argjson hp 1081 '
        {uuid:$uuid, publicKey:$pub, privateKey:$priv,
         shortId:$sid, serverName:$sni, host:$host, port:$port, flow:$flow,
         proxyUser:$pu, proxyPass:$pp, socksPort:$sp, httpPort:$hp}
    ' > "$SERVER_FILE"
    chown wisd:wisd "$SERVER_FILE"
    chmod 0640 "$SERVER_FILE"
fi

# Backfill proxy credentials for installs predating this feature.
if ! jq -e '.proxyUser' "$SERVER_FILE" >/dev/null 2>&1; then
    proxy_user=wisd_$(head -c 4 /dev/urandom | xxd -p -c 8)
    proxy_pass=$(head -c 18 /dev/urandom | base64 | tr -d '+/=' | head -c 24)
    tmp=$(mktemp)
    jq --arg pu "$proxy_user" --arg pp "$proxy_pass" \
       --argjson sp 1080 --argjson hp 1081 \
       '. + {proxyUser:$pu, proxyPass:$pp, socksPort:$sp, httpPort:$hp}' \
       "$SERVER_FILE" > "$tmp" && mv "$tmp" "$SERVER_FILE"
    chown wisd:wisd "$SERVER_FILE"
    chmod 0640 "$SERVER_FILE"
fi

step "Seed initial xray.json (direct mode, public auth-protected proxy)"
XRAY_CFG=$STATE_DIR/xray.json
if [[ ! -s "$XRAY_CFG" ]]; then
    s_uuid=$(jq -r '.uuid' "$SERVER_FILE")
    s_priv=$(jq -r '.privateKey' "$SERVER_FILE")
    s_short=$(jq -r '.shortId' "$SERVER_FILE")
    s_sni=$(jq -r '.serverName' "$SERVER_FILE")
    s_flow=$(jq -r '.flow' "$SERVER_FILE")
    s_pu=$(jq -r '.proxyUser' "$SERVER_FILE")
    s_pp=$(jq -r '.proxyPass' "$SERVER_FILE")
    s_sp=$(jq -r '.socksPort // 1080' "$SERVER_FILE")
    s_hp=$(jq -r '.httpPort // 1081' "$SERVER_FILE")
    s_vport=$(jq -r '.port // 2053' "$SERVER_FILE")
    jq -n --argjson vport "$s_vport" \
          --arg log "$LOG_DIR/xray.log" \
          --arg access "$LOG_DIR/access.log" \
          --arg uuid "$s_uuid" \
          --arg priv "$s_priv" \
          --arg short "$s_short" \
          --arg sni "$s_sni" \
          --arg flow "$s_flow" \
          --arg pu "$s_pu" \
          --arg pp "$s_pp" \
          --argjson sp "$s_sp" \
          --argjson hp "$s_hp" '
    {
      log: {loglevel:"warning", error:$log, access:$access},
      inbounds: [
        {tag:"vless-in", listen:"0.0.0.0", port:$vport, protocol:"vless",
         settings:{clients:[{id:$uuid, flow:$flow}], decryption:"none"},
         streamSettings:{network:"tcp", security:"reality",
            realitySettings:{show:false, dest:($sni+":443"), xver:0,
              serverNames:[$sni], privateKey:$priv, shortIds:[$short]}},
         sniffing:{enabled:true, destOverride:["http","tls","quic"]}},
        {tag:"socks-in", listen:"0.0.0.0", port:$sp, protocol:"socks",
         settings:{auth:"password", accounts:[{user:$pu, pass:$pp}], udp:true},
         sniffing:{enabled:true, destOverride:["http","tls","quic"]}},
        {tag:"http-in", listen:"0.0.0.0", port:$hp, protocol:"http",
         settings:{accounts:[{user:$pu, pass:$pp}]},
         sniffing:{enabled:true, destOverride:["http","tls","quic"]}}
      ],
      outbounds: [
        {tag:"direct", protocol:"freedom", settings:{}},
        {tag:"blocked", protocol:"blackhole", settings:{}}
      ],
      routing: {
        domainStrategy:"IPIfNonMatch",
        rules: [
          {type:"field", inboundTag:["vless-in","socks-in","http-in"], outboundTag:"direct"}
        ]
      }
    }' > "$XRAY_CFG"
    chown wisd:wisd "$XRAY_CFG"
    chmod 0664 "$XRAY_CFG"
fi
chown wisd:wisd "$XRAY_CFG"
chmod 0664 "$XRAY_CFG"

step "Install systemd unit"
install -m 0644 "$REPO_DIR/deploy/wisd-xray.service" /etc/systemd/system/wisd-xray.service
systemctl daemon-reload
systemctl enable wisd-xray.service
systemctl restart wisd-xray.service

step "Enable BBR + tuned sysctl (VPN stability)"
install -m 0644 "$REPO_DIR/deploy/wisd-sysctl.conf" /etc/sysctl.d/99-wisd-net.conf
sysctl -p /etc/sysctl.d/99-wisd-net.conf | tail -3 || true

step "Install sing-box (Hysteria2 UDP transport)"
SB_VERSION=${SB_VERSION:-1.10.7}
if [[ ! -x /usr/local/bin/sing-box ]] || ! /usr/local/bin/sing-box version 2>/dev/null | grep -q "$SB_VERSION"; then
    tmp=$(mktemp -d)
    sb_arch=$(uname -m)
    case "$sb_arch" in
        x86_64|amd64) sb_zip="sing-box-${SB_VERSION}-linux-amd64.tar.gz"; sb_dir="sing-box-${SB_VERSION}-linux-amd64" ;;
        aarch64|arm64) sb_zip="sing-box-${SB_VERSION}-linux-arm64.tar.gz"; sb_dir="sing-box-${SB_VERSION}-linux-arm64" ;;
        *) echo "Unsupported arch for sing-box: $sb_arch"; exit 1 ;;
    esac
    curl -fsSL -o "$tmp/sb.tar.gz" "https://github.com/SagerNet/sing-box/releases/download/v${SB_VERSION}/${sb_zip}"
    tar -xzf "$tmp/sb.tar.gz" -C "$tmp"
    install -m 0755 "$tmp/$sb_dir/sing-box" /usr/local/bin/sing-box
    rm -rf "$tmp"
fi

step "Generate Hysteria2 + TUIC + ShadowTLS secrets + self-signed cert"
HY2_DIR=/etc/wisd-hy2
mkdir -p "$HY2_DIR"

# Hysteria2 + port-hopping range
if ! jq -e '.hy2Pass' "$SERVER_FILE" >/dev/null 2>&1; then
    hy2_pass=$(head -c 24 /dev/urandom | base64 | tr -d '+/=' | head -c 32)
    hy2_sni=${WISD_HY2_SNI:-www.bing.com}
    tmp=$(mktemp)
    jq --arg pw "$hy2_pass" --arg sni "$hy2_sni" --argjson port 443 \
       --argjson plo 30000 --argjson phi 50000 \
       '. + {hy2Pass:$pw, hy2Sni:$sni, hy2Port:$port, hy2PortLow:$plo, hy2PortHigh:$phi}' \
       "$SERVER_FILE" > "$tmp" && mv "$tmp" "$SERVER_FILE"
    chown wisd:wisd "$SERVER_FILE"
    chmod 0640 "$SERVER_FILE"
fi

# TUIC v5 (alt UDP transport — different fingerprint vs Hysteria2)
if ! jq -e '.tuicUuid' "$SERVER_FILE" >/dev/null 2>&1; then
    tuic_uuid=$(cat /proc/sys/kernel/random/uuid)
    tuic_pass=$(head -c 18 /dev/urandom | base64 | tr -d '+/=' | head -c 24)
    tmp=$(mktemp)
    jq --arg tu "$tuic_uuid" --arg tp "$tuic_pass" --argjson tport 8443 \
       '. + {tuicUuid:$tu, tuicPass:$tp, tuicPort:$tport}' \
       "$SERVER_FILE" > "$tmp" && mv "$tmp" "$SERVER_FILE"
    chown wisd:wisd "$SERVER_FILE"; chmod 0640 "$SERVER_FILE"
fi

# ShadowTLS v3 + Shadowsocks-2022 (TCP, masks as Russian whitelisted site)
if ! jq -e '.stlsPass' "$SERVER_FILE" >/dev/null 2>&1; then
    stls_pass=$(head -c 24 /dev/urandom | base64 | tr -d '+/=' | head -c 32)
    ss_pass=$(head -c 16 /dev/urandom | base64 -w0)
    tmp=$(mktemp)
    jq --arg sp "$stls_pass" --arg ss "$ss_pass" \
       --arg sh "${WISD_STLS_HOST:-vk.com}" --argjson stp 8443 \
       '. + {stlsPass:$sp, ssPass:$ss, stlsHandshakeHost:$sh, stlsPort:$stp}' \
       "$SERVER_FILE" > "$tmp" && mv "$tmp" "$SERVER_FILE"
    chown wisd:wisd "$SERVER_FILE"; chmod 0640 "$SERVER_FILE"
fi

# VLESS-WS endpoint (used by Cloudflare Worker relay for whitelist bypass)
if ! jq -e '.wsPath' "$SERVER_FILE" >/dev/null 2>&1; then
    wsws_path=/$(head -c 6 /dev/urandom | xxd -p -c 12)
    tmp=$(mktemp)
    jq --arg wp "$wsws_path" --argjson wpp 10443 \
       '. + {wsPath:$wp, wsPort:$wpp}' \
       "$SERVER_FILE" > "$tmp" && mv "$tmp" "$SERVER_FILE"
    chown wisd:wisd "$SERVER_FILE"; chmod 0640 "$SERVER_FILE"
fi

HY2_PASS=$(jq -r '.hy2Pass' "$SERVER_FILE")
HY2_SNI=$(jq -r '.hy2Sni' "$SERVER_FILE")
HY2_PORT=$(jq -r '.hy2Port' "$SERVER_FILE")
TUIC_UUID=$(jq -r '.tuicUuid' "$SERVER_FILE")
TUIC_PASS=$(jq -r '.tuicPass' "$SERVER_FILE")
TUIC_PORT=$(jq -r '.tuicPort' "$SERVER_FILE")
STLS_PASS=$(jq -r '.stlsPass' "$SERVER_FILE")
SS_PASS=$(jq -r '.ssPass' "$SERVER_FILE")
STLS_HH=$(jq -r '.stlsHandshakeHost' "$SERVER_FILE")
STLS_PORT=$(jq -r '.stlsPort' "$SERVER_FILE")

if [[ ! -f "$HY2_DIR/cert.crt" ]]; then
    openssl ecparam -genkey -name prime256v1 -out "$HY2_DIR/private.key"
    openssl req -new -x509 -days 3650 -key "$HY2_DIR/private.key" \
        -out "$HY2_DIR/cert.crt" -subj "/CN=$HY2_SNI" 2>/dev/null
    chown root:root "$HY2_DIR/cert.crt" "$HY2_DIR/private.key"
    chmod 0644 "$HY2_DIR/cert.crt"
    chmod 0600 "$HY2_DIR/private.key"
fi

step "Write sing-box config (Hysteria2 + TUIC + ShadowTLS-SS)"
cat > "$HY2_DIR/sing-box.json" <<JSON
{
  "log": { "level": "warn", "timestamp": true },
  "inbounds": [
    {
      "type": "hysteria2",
      "tag": "hy2-in",
      "listen": "::",
      "listen_port": ${HY2_PORT},
      "up_mbps": 1000,
      "down_mbps": 1000,
      "users": [{ "name": "wisd", "password": "${HY2_PASS}" }],
      "masquerade": "https://${HY2_SNI}",
      "tls": {
        "enabled": true,
        "server_name": "${HY2_SNI}",
        "alpn": ["h3"],
        "certificate_path": "/etc/wisd-hy2/cert.crt",
        "key_path": "/etc/wisd-hy2/private.key"
      }
    },
    {
      "type": "tuic",
      "tag": "tuic-in",
      "listen": "::",
      "listen_port": ${TUIC_PORT},
      "users": [{ "uuid": "${TUIC_UUID}", "password": "${TUIC_PASS}" }],
      "congestion_control": "bbr",
      "auth_timeout": "3s",
      "zero_rtt_handshake": false,
      "heartbeat": "10s",
      "tls": {
        "enabled": true,
        "server_name": "${HY2_SNI}",
        "alpn": ["h3"],
        "certificate_path": "/etc/wisd-hy2/cert.crt",
        "key_path": "/etc/wisd-hy2/private.key"
      }
    },
    {
      "type": "shadowtls",
      "tag": "stls-in",
      "listen": "::",
      "listen_port": ${STLS_PORT},
      "version": 3,
      "users": [{ "name": "wisd", "password": "${STLS_PASS}" }],
      "handshake": { "server": "${STLS_HH}", "server_port": 443 },
      "strict_mode": true,
      "detour": "ss-in"
    },
    {
      "type": "shadowsocks",
      "tag": "ss-in",
      "listen": "127.0.0.1",
      "listen_port": 8388,
      "method": "2022-blake3-aes-128-gcm",
      "password": "${SS_PASS}"
    }
  ],
  "outbounds": [
    { "type": "direct", "tag": "direct" },
    { "type": "block", "tag": "block" }
  ]
}
JSON
chmod 0644 "$HY2_DIR/sing-box.json"

step "Install Hysteria2 systemd unit"
install -m 0644 "$REPO_DIR/deploy/wisd-hy2.service" /etc/systemd/system/wisd-hy2.service
systemctl daemon-reload
systemctl enable wisd-hy2.service
systemctl restart wisd-hy2.service

step "Set up Hysteria2 port-hopping (UDP $(jq -r '.hy2PortLow' "$SERVER_FILE")-$(jq -r '.hy2PortHigh' "$SERVER_FILE") -> :$HY2_PORT)"
HY2_LO=$(jq -r '.hy2PortLow' "$SERVER_FILE")
HY2_HI=$(jq -r '.hy2PortHigh' "$SERVER_FILE")
mkdir -p /etc/nftables.d
cat > /etc/nftables.d/wisd-hop.conf <<NFT
table inet wisd_hop {
    chain prerouting {
        type nat hook prerouting priority dstnat; policy accept;
        udp dport ${HY2_LO}-${HY2_HI} redirect to :${HY2_PORT}
    }
}
NFT
if ! grep -q 'include "/etc/nftables.d/' /etc/nftables.conf 2>/dev/null; then
    echo 'include "/etc/nftables.d/*.conf"' >> /etc/nftables.conf
fi
nft delete table inet wisd_hop 2>/dev/null || true
nft -f /etc/nftables.d/wisd-hop.conf
systemctl enable nftables.service 2>/dev/null || true
systemctl restart nftables.service 2>/dev/null || true

step "Bootstrap admin credentials + session key + subscription token"
ADMIN_FILE=$STATE_DIR/admin.json
SESSION_KEY=$STATE_DIR/session.key
ADMIN_TXT=$STATE_DIR/admin.txt
SUB_TOKEN_FILE=$STATE_DIR/sub.token

# Public token for the /sub endpoint (long-lived; can be rotated from the panel).
if [[ ! -s "$SUB_TOKEN_FILE" ]]; then
    head -c 32 /dev/urandom | xxd -p -c 64 | tr -d '\n' > "$SUB_TOKEN_FILE"
    printf '\n' >> "$SUB_TOKEN_FILE"
    chown wisd:www-data "$SUB_TOKEN_FILE"
    chmod 0640 "$SUB_TOKEN_FILE"
fi

# Random 32-byte session signing key (HMAC-SHA256).
if [[ ! -s "$SESSION_KEY" ]]; then
    head -c 48 /dev/urandom | base64 -w0 > "$SESSION_KEY"
    chown wisd:www-data "$SESSION_KEY"
    chmod 0640 "$SESSION_KEY"
fi

# Admin user + bcrypt-equivalent (PBKDF2-SHA256) password hash.
if [[ ! -s "$ADMIN_FILE" ]]; then
    admin_user=${WISD_ADMIN_USER:-admin}
    admin_pass=${WISD_ADMIN_PASS:-$(head -c 18 /dev/urandom | base64 | tr -d '+/=' | head -c 20)}
    admin_hash=$(python3 "$REPO_DIR/site/cgi-bin/wisd_auth.py" hash "$admin_pass")
    jq -n --arg u "$admin_user" --arg h "$admin_hash" \
        '{user:$u, passHash:$h}' > "$ADMIN_FILE"
    chown wisd:www-data "$ADMIN_FILE"
    chmod 0640 "$ADMIN_FILE"
    # Plaintext copy for the operator (root-only) so they can recover the
    # initial password without re-running with WISD_ADMIN_PASS.
    umask 077
    printf 'wisd admin credentials\nuser: %s\npass: %s\n' "$admin_user" "$admin_pass" > "$ADMIN_TXT"
    umask 022
    chown root:root "$ADMIN_TXT"
    chmod 0600 "$ADMIN_TXT"
fi

step "Install nginx site"
install -m 0644 "$REPO_DIR/deploy/wisd.nginx.conf" /etc/nginx/sites-available/wisd
ln -sf /etc/nginx/sites-available/wisd /etc/nginx/sites-enabled/wisd
rm -f /etc/nginx/sites-enabled/default

# Generate the WS-passthrough location block (sourced from server.json).
WS_PATH=$(jq -r '.wsPath // ""' "$SERVER_FILE")
WS_PORT=$(jq -r '.wsPort // 0' "$SERVER_FILE")
if [[ -n "$WS_PATH" && "$WS_PATH" != "null" && "$WS_PORT" -gt 0 ]]; then
    cat > /etc/nginx/wisd-ws.location <<NGINX
location ${WS_PATH} {
    if (\$http_upgrade != "websocket") {
        return 404;
    }
    proxy_pass http://127.0.0.1:${WS_PORT};
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection \$wisd_ws_upgrade;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
NGINX
else
    rm -f /etc/nginx/wisd-ws.location
fi

step "Configure HTTP mode (panel-on-HTTP or redirect-to-HTTPS)"
# Reusable helper: write the auth-protected location blocks (used by both
# the HTTP fallback and the HTTPS server block).
write_panel_locations() {
    local out=$1
    cat > "$out" <<'NGINX'
# Public (no auth) — login page, its assets, login/logout CGI, ACME, favicon.
location = /login.html { try_files /login.html =404; }
location = /favicon.ico { try_files /assets/icon.svg =404; }
location ^~ /assets/ { try_files $uri =404; }
location = /cgi-bin/login.cgi {
    gzip off;
    include /etc/nginx/fastcgi_params;
    fastcgi_pass unix:/run/fcgiwrap.socket;
    fastcgi_param SCRIPT_FILENAME /var/www/wisd$fastcgi_script_name;
    fastcgi_param DOCUMENT_ROOT /var/www/wisd;
    fastcgi_read_timeout 60s;
}
location = /cgi-bin/logout.cgi {
    gzip off;
    include /etc/nginx/fastcgi_params;
    fastcgi_pass unix:/run/fcgiwrap.socket;
    fastcgi_param SCRIPT_FILENAME /var/www/wisd$fastcgi_script_name;
    fastcgi_param DOCUMENT_ROOT /var/www/wisd;
    fastcgi_read_timeout 10s;
}
# Public subscription endpoint (token-protected, no cookie auth).
location = /sub {
    gzip off;
    include /etc/nginx/fastcgi_params;
    fastcgi_pass unix:/run/fcgiwrap.socket;
    fastcgi_param SCRIPT_FILENAME /var/www/wisd/cgi-bin/sub.cgi;
    fastcgi_param SCRIPT_NAME /cgi-bin/sub.cgi;
    fastcgi_param DOCUMENT_ROOT /var/www/wisd;
    fastcgi_read_timeout 30s;
}
# Internal subrequest endpoint for auth_request.
location = /__auth {
    internal;
    include /etc/nginx/fastcgi_params;
    fastcgi_pass unix:/run/fcgiwrap.socket;
    fastcgi_param SCRIPT_FILENAME /var/www/wisd/cgi-bin/auth.cgi;
    fastcgi_param SCRIPT_NAME /cgi-bin/auth.cgi;
    fastcgi_param REQUEST_METHOD GET;
    fastcgi_param QUERY_STRING "";
    fastcgi_param CONTENT_TYPE "";
    fastcgi_param CONTENT_LENGTH "";
    fastcgi_pass_request_body off;
}
# Protected: static files (HTML/JS/CSS).
location / {
    auth_request /__auth;
    error_page 401 = @to_login;
    try_files $uri $uri/ =404;
}
# Protected: all other CGI.
location ^~ /cgi-bin/ {
    auth_request /__auth;
    error_page 401 = @auth_json_401;
    gzip off;
    include /etc/nginx/fastcgi_params;
    fastcgi_pass unix:/run/fcgiwrap.socket;
    fastcgi_param SCRIPT_FILENAME /var/www/wisd$fastcgi_script_name;
    fastcgi_param DOCUMENT_ROOT /var/www/wisd;
    fastcgi_read_timeout 60s;
}
location @to_login {
    return 302 /login.html?next=$request_uri;
}
location @auth_json_401 {
    default_type application/json;
    return 401 '{"ok":false,"code":401,"message":"auth required"}';
}
NGINX
}

WISD_DOMAIN=${WISD_DOMAIN:-}
TLS_PORT=${WISD_TLS_PORT:-443}
if [[ "$TLS_PORT" == "443" ]]; then
    TLS_HOST_SUFFIX=""
else
    TLS_HOST_SUFFIX=":${TLS_PORT}"
fi
CERT_DIR=""
if [[ -n "$WISD_DOMAIN" ]]; then
    CERT_DIR="/etc/letsencrypt/live/$WISD_DOMAIN"
fi

if [[ -n "$WISD_DOMAIN" && -s "$CERT_DIR/fullchain.pem" ]]; then
    # TLS is set up — :80 redirects to HTTPS, panel served from :${TLS_PORT}.
    cat > /etc/nginx/wisd-http-mode.conf <<NGINX
location / {
    return 301 https://\$host${TLS_HOST_SUFFIX}\$request_uri;
}
NGINX
    # HTTPS server with auth-protected panel.
    write_panel_locations /tmp/wisd-https-locations.conf
    {
        cat <<NGINX
server {
    listen ${TLS_PORT} ssl http2 default_server;
    listen [::]:${TLS_PORT} ssl http2 default_server;
    server_name ${WISD_DOMAIN} www.${WISD_DOMAIN};

    ssl_certificate     ${CERT_DIR}/fullchain.pem;
    ssl_certificate_key ${CERT_DIR}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_session_cache shared:wisd_ssl:8m;
    ssl_session_timeout 1d;
    add_header Strict-Transport-Security "max-age=15552000" always;

    root /var/www/wisd;
    index index.html;

    access_log /var/log/nginx/wisd-https.access.log;
    error_log  /var/log/nginx/wisd-https.error.log;

    client_max_body_size 1m;

NGINX
        cat /tmp/wisd-https-locations.conf
        printf '}\n'
    } > /etc/nginx/wisd-https.server
    rm -f /tmp/wisd-https-locations.conf
else
    # No TLS / no domain — panel served over plain HTTP on :80.
    # Apply the same auth-protected location blocks.
    write_panel_locations /etc/nginx/wisd-http-mode.conf
    rm -f /etc/nginx/wisd-https.server
fi

nginx -t
systemctl restart nginx
systemctl enable fcgiwrap.socket fcgiwrap.service 2>/dev/null || true
systemctl restart fcgiwrap.socket 2>/dev/null || systemctl restart fcgiwrap || true

if [[ -n "$WISD_DOMAIN" && ! -s "$CERT_DIR/fullchain.pem" ]]; then
    step "Obtain Let's Encrypt cert for $WISD_DOMAIN"
    mkdir -p /var/www/html
    domains="-d $WISD_DOMAIN"
    if getent hosts "www.$WISD_DOMAIN" >/dev/null 2>&1; then
        domains="$domains -d www.$WISD_DOMAIN"
    fi
    if certbot certonly --webroot -w /var/www/html \
            --non-interactive --agree-tos \
            --email "${WISD_LE_EMAIL:-admin@$WISD_DOMAIN}" \
            $domains; then
        # Switch HTTP mode to redirect, install HTTPS server block, reload.
        cat > /etc/nginx/wisd-http-mode.conf <<NGINX
location / {
    return 301 https://\$host${TLS_HOST_SUFFIX}\$request_uri;
}
NGINX
        write_panel_locations /tmp/wisd-https-locations.conf
        {
            cat <<NGINX
server {
    listen ${TLS_PORT} ssl http2 default_server;
    listen [::]:${TLS_PORT} ssl http2 default_server;
    server_name ${WISD_DOMAIN} www.${WISD_DOMAIN};

    ssl_certificate     ${CERT_DIR}/fullchain.pem;
    ssl_certificate_key ${CERT_DIR}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_session_cache shared:wisd_ssl:8m;
    ssl_session_timeout 1d;
    add_header Strict-Transport-Security "max-age=15552000" always;

    root /var/www/wisd;
    index index.html;

    access_log /var/log/nginx/wisd-https.access.log;
    error_log  /var/log/nginx/wisd-https.error.log;

    client_max_body_size 1m;

NGINX
            cat /tmp/wisd-https-locations.conf
            printf '}\n'
        } > /etc/nginx/wisd-https.server
        rm -f /tmp/wisd-https-locations.conf
        nginx -t && systemctl reload nginx
        if [[ "$TLS_PORT" == "443" ]]; then
            echo "TLS configured: https://$WISD_DOMAIN/"
        else
            echo "TLS configured: https://$WISD_DOMAIN:${TLS_PORT}/"
        fi
    else
        echo "!! certbot failed for $WISD_DOMAIN — staying on HTTP for now."
        echo "!! Check that the A record for $WISD_DOMAIN points at this VPS and re-run with WISD_DOMAIN=$WISD_DOMAIN."
    fi
fi

step "Deploy site files to $WEB_ROOT"
mkdir -p "$WEB_ROOT"
cp -a "$REPO_DIR/site/." "$WEB_ROOT/"
chown -R www-data:www-data "$WEB_ROOT"
chmod -R 0755 "$WEB_ROOT"
find "$WEB_ROOT/cgi-bin" -name '*.cgi' -exec chmod 0755 {} +

step "Install sudoers entry"
install -m 0440 "$REPO_DIR/deploy/wisd-cgi.sudoers" /etc/sudoers.d/wisd-cgi
visudo -c -f /etc/sudoers.d/wisd-cgi

step "Open firewall ports (if ufw is active)"
if command -v ufw >/dev/null 2>&1; then
    ufw status | grep -q "Status: active" && {
        s_sp=$(jq -r '.socksPort // 1080' "$SERVER_FILE")
        s_hp=$(jq -r '.httpPort // 1081' "$SERVER_FILE")
        hy2_port=$(jq -r '.hy2Port // 443' "$SERVER_FILE")
        hy2_lo=$(jq -r '.hy2PortLow // 30000' "$SERVER_FILE")
        hy2_hi=$(jq -r '.hy2PortHigh // 50000' "$SERVER_FILE")
        ufw allow 80/tcp >/dev/null
        ufw allow 443/tcp >/dev/null
        ufw allow "${WISD_TLS_PORT:-443}/tcp" >/dev/null
        ufw allow "${WISD_VLESS_PORT:-2053}/tcp" >/dev/null
        ufw allow "$s_sp/tcp" >/dev/null
        ufw allow "$s_hp/tcp" >/dev/null
        ufw allow "$hy2_port/udp" >/dev/null
        ufw allow "${hy2_lo}:${hy2_hi}/udp" >/dev/null
        ufw reload >/dev/null
    }
fi

step "Save client URLs"
pubip=$(jq -r '.host' "$SERVER_FILE")
uuid=$(jq -r '.uuid' "$SERVER_FILE")
pub=$(jq -r '.publicKey' "$SERVER_FILE")
sid=$(jq -r '.shortId' "$SERVER_FILE")
sni=$(jq -r '.serverName' "$SERVER_FILE")
flow=$(jq -r '.flow' "$SERVER_FILE")
hy2_pass=$(jq -r '.hy2Pass' "$SERVER_FILE")
hy2_sni=$(jq -r '.hy2Sni' "$SERVER_FILE")
hy2_port=$(jq -r '.hy2Port' "$SERVER_FILE")
hy2_lo=$(jq -r '.hy2PortLow' "$SERVER_FILE")
hy2_hi=$(jq -r '.hy2PortHigh' "$SERVER_FILE")
echo "vless://${uuid}@${pubip}:443?encryption=none&security=reality&sni=${sni}&fp=chrome&pbk=${pub}&sid=${sid}&type=tcp&flow=${flow}#wisd-${pubip}" \
    > "$STATE_DIR/client_url.txt"
echo "hysteria2://${hy2_pass}@${pubip}:${hy2_port}?insecure=1&sni=${hy2_sni}&mport=${hy2_lo}-${hy2_hi}#wisd-hy2-${pubip}" \
    > "$STATE_DIR/hy2_url.txt"
chown wisd:wisd "$STATE_DIR/client_url.txt" "$STATE_DIR/hy2_url.txt"

step "Done"
if [[ -n "${WISD_DOMAIN:-}" && -s "/etc/letsencrypt/live/$WISD_DOMAIN/fullchain.pem" ]]; then
    panel_port=${TLS_PORT:-443}
    if [[ "$panel_port" == "443" ]]; then
        echo "Panel:        https://$WISD_DOMAIN/"
    else
        echo "Panel:        https://$WISD_DOMAIN:${panel_port}/"
    fi
else
    echo "Panel:        http://$pubip/"
fi
echo "Admin file:   $ADMIN_TXT  (root-only, contains initial password)"
if [[ -s "$ADMIN_TXT" ]]; then
    echo "---"
    cat "$ADMIN_TXT"
    echo "---"
fi
echo "VLESS URL:    $(cat "$STATE_DIR/client_url.txt")"
echo "Hysteria2 URL: $(cat "$STATE_DIR/hy2_url.txt")"
echo "State dir:    $STATE_DIR"
echo "Logs:         $LOG_DIR"
