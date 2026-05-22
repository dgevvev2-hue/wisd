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
    nginx fcgiwrap jq curl ca-certificates unzip uuid-runtime python3 xxd sudo
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

step "Generate VLESS-Reality server keys"
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
    jq -n --arg uuid "$uuid" \
          --arg pub "$pub" \
          --arg priv "$priv" \
          --arg sid "$short_id" \
          --arg sni "$server_name" \
          --arg host "$pubip" \
          --argjson port 443 \
          --arg flow "xtls-rprx-vision" '
        {uuid:$uuid, publicKey:$pub, privateKey:$priv,
         shortId:$sid, serverName:$sni, host:$host, port:$port, flow:$flow}
    ' > "$SERVER_FILE"
    chown wisd:wisd "$SERVER_FILE"
    chmod 0640 "$SERVER_FILE"
fi

step "Seed initial xray.json (direct mode)"
XRAY_CFG=$STATE_DIR/xray.json
if [[ ! -s "$XRAY_CFG" ]]; then
    s_uuid=$(jq -r '.uuid' "$SERVER_FILE")
    s_priv=$(jq -r '.privateKey' "$SERVER_FILE")
    s_short=$(jq -r '.shortId' "$SERVER_FILE")
    s_sni=$(jq -r '.serverName' "$SERVER_FILE")
    s_flow=$(jq -r '.flow' "$SERVER_FILE")
    jq -n --arg log "$LOG_DIR/xray.log" \
          --arg access "$LOG_DIR/access.log" \
          --arg uuid "$s_uuid" \
          --arg priv "$s_priv" \
          --arg short "$s_short" \
          --arg sni "$s_sni" \
          --arg flow "$s_flow" '
    {
      log: {loglevel:"warning", error:$log, access:$access},
      inbounds: [
        {tag:"vless-in", listen:"0.0.0.0", port:443, protocol:"vless",
         settings:{clients:[{id:$uuid, flow:$flow}], decryption:"none"},
         streamSettings:{network:"tcp", security:"reality",
            realitySettings:{show:false, dest:($sni+":443"), xver:0,
              serverNames:[$sni], privateKey:$priv, shortIds:[$short]}},
         sniffing:{enabled:true, destOverride:["http","tls","quic"]}},
        {tag:"socks-in", listen:"127.0.0.1", port:1080, protocol:"socks",
         settings:{auth:"noauth", udp:true}},
        {tag:"http-in", listen:"127.0.0.1", port:1081, protocol:"http",
         settings:{}}
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

step "Install nginx site"
install -m 0644 "$REPO_DIR/deploy/wisd.nginx.conf" /etc/nginx/sites-available/wisd
ln -sf /etc/nginx/sites-available/wisd /etc/nginx/sites-enabled/wisd
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx
systemctl enable fcgiwrap.socket fcgiwrap.service 2>/dev/null || true
systemctl restart fcgiwrap.socket 2>/dev/null || systemctl restart fcgiwrap || true

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
        ufw allow 80/tcp >/dev/null
        ufw allow 443/tcp >/dev/null
        ufw reload >/dev/null
    }
fi

step "Save client VLESS URL"
pubip=$(jq -r '.host' "$SERVER_FILE")
uuid=$(jq -r '.uuid' "$SERVER_FILE")
pub=$(jq -r '.publicKey' "$SERVER_FILE")
sid=$(jq -r '.shortId' "$SERVER_FILE")
sni=$(jq -r '.serverName' "$SERVER_FILE")
flow=$(jq -r '.flow' "$SERVER_FILE")
echo "vless://${uuid}@${pubip}:443?encryption=none&security=reality&sni=${sni}&fp=chrome&pbk=${pub}&sid=${sid}&type=tcp&flow=${flow}#wisd-${pubip}" \
    > "$STATE_DIR/client_url.txt"
chown wisd:wisd "$STATE_DIR/client_url.txt"

step "Done"
echo "Panel:      http://$pubip/"
echo "VLESS URL:  $(cat "$STATE_DIR/client_url.txt")"
echo "State dir:  $STATE_DIR"
echo "Logs:       $LOG_DIR"
