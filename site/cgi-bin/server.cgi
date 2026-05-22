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

if [[ -z "$host" || "$host" == "null" ]]; then
    host=$(curl -s --max-time 2 https://ifconfig.io 2>/dev/null)
    [[ -z "$host" ]] && host=$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | head -1 | cut -d/ -f1)
fi

vless_url="vless://${uuid}@${host}:${port}?encryption=none&security=reality&sni=${server_name}&fp=chrome&pbk=${public_key}&sid=${short_id}&type=tcp&flow=${flow}#wisd-${host}"

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
  "url": "$(json_escape "$vless_url")"
}
JSON
