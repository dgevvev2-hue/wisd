#!/bin/bash
# server.cgi -- expose info about this VPS as a VLESS server (so users
# can build a client URL to connect TO this box).
DIR=$(dirname "$0")
. "$DIR/lib.sh"
require_jq

json_header

if [[ ! -f "$WISD_SERVER_FILE" ]]; then
    printf '{"ok":false,"message":"server not configured yet"}\n'
    exit 0
fi

uuid=$(jq -r '.uuid // ""' "$WISD_SERVER_FILE")
public_key=$(jq -r '.publicKey // ""' "$WISD_SERVER_FILE")
short_id=$(jq -r '.shortId // ""' "$WISD_SERVER_FILE")
server_name=$(jq -r '.serverName // "www.cloudflare.com"' "$WISD_SERVER_FILE")
port=$(jq -r '.port // 443' "$WISD_SERVER_FILE")
host=$(jq -r '.host // ""' "$WISD_SERVER_FILE")
flow=$(jq -r '.flow // "xtls-rprx-vision"' "$WISD_SERVER_FILE")
proxy_user=$(jq -r '.proxyUser // ""' "$WISD_SERVER_FILE")
proxy_pass=$(jq -r '.proxyPass // ""' "$WISD_SERVER_FILE")
socks_port=$(jq -r '.socksPort // 1080' "$WISD_SERVER_FILE")
http_port=$(jq -r '.httpPort // 1081' "$WISD_SERVER_FILE")
hy2_pass=$(jq -r '.hy2Pass // ""' "$WISD_SERVER_FILE")
hy2_sni=$(jq -r '.hy2Sni // ""' "$WISD_SERVER_FILE")
hy2_port=$(jq -r '.hy2Port // 443' "$WISD_SERVER_FILE")
hy2_port_low=$(jq -r '.hy2PortLow // 0' "$WISD_SERVER_FILE")
hy2_port_high=$(jq -r '.hy2PortHigh // 0' "$WISD_SERVER_FILE")
tuic_uuid=$(jq -r '.tuicUuid // ""' "$WISD_SERVER_FILE")
tuic_pass=$(jq -r '.tuicPass // ""' "$WISD_SERVER_FILE")
tuic_port=$(jq -r '.tuicPort // 0' "$WISD_SERVER_FILE")
stls_pass=$(jq -r '.stlsPass // ""' "$WISD_SERVER_FILE")
ss_pass=$(jq -r '.ssPass // ""' "$WISD_SERVER_FILE")
stls_hh=$(jq -r '.stlsHandshakeHost // ""' "$WISD_SERVER_FILE")
stls_port=$(jq -r '.stlsPort // 0' "$WISD_SERVER_FILE")
ws_path=$(jq -r '.wsPath // ""' "$WISD_SERVER_FILE")
ws_port=$(jq -r '.wsPort // 0' "$WISD_SERVER_FILE")
cf_host=$(jq -r '.cfWorkerHost // ""' "$WISD_SERVER_FILE")

if [[ -z "$host" || "$host" == "null" ]]; then
    host=$(curl -s --max-time 2 https://ifconfig.io 2>/dev/null)
    [[ -z "$host" ]] && host=$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | head -1 | cut -d/ -f1)
fi

vless_url="vless://${uuid}@${host}:${port}?encryption=none&security=reality&sni=${server_name}&fp=chrome&pbk=${public_key}&sid=${short_id}&type=tcp&flow=${flow}#wisd-${host}"

# URL-encode user/pass for curl-style proxy URLs (basic: replace common specials).
url_encode() {
    local s=$1 i c out=""
    for ((i=0; i<${#s}; i++)); do
        c=${s:i:1}
        case "$c" in
            [A-Za-z0-9._~-]) out+="$c" ;;
            *) printf -v c '%%%02X' "'$c"; out+="$c" ;;
        esac
    done
    printf '%s' "$out"
}
pu_enc=$(url_encode "$proxy_user")
pp_enc=$(url_encode "$proxy_pass")
socks_url="socks5://${pu_enc}:${pp_enc}@${host}:${socks_port}"
http_url="http://${pu_enc}:${pp_enc}@${host}:${http_port}"

hy2_url=""
if [[ -n "$hy2_pass" && -n "$hy2_sni" ]]; then
    hy2_pass_enc=$(url_encode "$hy2_pass")
    if [[ "$hy2_port_low" -gt 0 && "$hy2_port_high" -gt 0 ]]; then
        hy2_url="hysteria2://${hy2_pass_enc}@${host}:${hy2_port}?insecure=1&sni=${hy2_sni}&mport=${hy2_port_low}-${hy2_port_high}#wisd-hy2-${host}"
    else
        hy2_url="hysteria2://${hy2_pass_enc}@${host}:${hy2_port}?insecure=1&sni=${hy2_sni}#wisd-hy2-${host}"
    fi
fi

tuic_url=""
if [[ -n "$tuic_uuid" && -n "$tuic_pass" && "$tuic_port" -gt 0 ]]; then
    tuic_pass_enc=$(url_encode "$tuic_pass")
    tuic_url="tuic://${tuic_uuid}:${tuic_pass_enc}@${host}:${tuic_port}?congestion_control=bbr&alpn=h3&sni=${hy2_sni}&allow_insecure=1&udp_relay_mode=native#wisd-tuic-${host}"
fi

cf_url=""
cf_ws_url=""
direct_ws_url=""
if [[ -n "$ws_path" && "$ws_port" -gt 0 ]]; then
    ws_path_enc=$(url_encode "$ws_path")
    # Direct (plain) connect — only works when network allows our IP
    direct_ws_url="vless://${uuid}@${host}:${ws_port}?encryption=none&security=none&type=ws&path=${ws_path_enc}&host=${host}#wisd-ws-direct"
    if [[ -n "$cf_host" ]]; then
        # CF-proxied — connect to Worker hostname, which forwards to VPS:80/<wsPath>
        cf_ws_url="vless://${uuid}@${cf_host}:443?encryption=none&security=tls&type=ws&path=${ws_path_enc}&host=${cf_host}&sni=${cf_host}&fp=chrome#wisd-cf-ws"
        cf_url="$cf_ws_url"
    fi
fi

cat <<JSON
{
  "ok": true,
  "host": "$(json_escape "$host")",
  "port": $port,
  "uuid": "$(json_escape "$uuid")",
  "publicKey": "$(json_escape "$public_key")",
  "shortId": "$(json_escape "$short_id")",
  "serverName": "$(json_escape "$server_name")",
  "flow": "$(json_escape "$flow")",
  "url": "$(json_escape "$vless_url")",
  "proxy": {
    "socksPort": $socks_port,
    "httpPort": $http_port,
    "user": "$(json_escape "$proxy_user")",
    "pass": "$(json_escape "$proxy_pass")",
    "socksUrl": "$(json_escape "$socks_url")",
    "httpUrl": "$(json_escape "$http_url")"
  },
  "hysteria2": {
    "port": $hy2_port,
    "portLow": $hy2_port_low,
    "portHigh": $hy2_port_high,
    "sni": "$(json_escape "$hy2_sni")",
    "pass": "$(json_escape "$hy2_pass")",
    "url": "$(json_escape "$hy2_url")"
  },
  "tuic": {
    "port": $tuic_port,
    "uuid": "$(json_escape "$tuic_uuid")",
    "pass": "$(json_escape "$tuic_pass")",
    "sni": "$(json_escape "$hy2_sni")",
    "url": "$(json_escape "$tuic_url")"
  },
  "shadowtls": {
    "port": $stls_port,
    "handshakeHost": "$(json_escape "$stls_hh")",
    "stlsPass": "$(json_escape "$stls_pass")",
    "ssPass": "$(json_escape "$ss_pass")",
    "ssMethod": "2022-blake3-aes-128-gcm"
  },
  "ws": {
    "port": $ws_port,
    "path": "$(json_escape "$ws_path")",
    "directUrl": "$(json_escape "$direct_ws_url")",
    "cfHost": "$(json_escape "$cf_host")",
    "cfUrl": "$(json_escape "$cf_ws_url")"
  }
}
JSON
