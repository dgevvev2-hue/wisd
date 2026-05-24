#!/bin/bash
# sub-info.cgi -- return the current subscription URL + token to the panel.
# Auth-gated via nginx auth_request.

set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib.sh"

TOKEN_FILE=$WISD_STATE_DIR/sub.token
if [[ ! -s "$TOKEN_FILE" ]]; then
    # Auto-bootstrap on first call.
    new=$(head -c 32 /dev/urandom | xxd -p -c 64 | tr -d '\n')
    printf '%s\n' "$new" > "$TOKEN_FILE.tmp"
    chown wisd:wisd "$TOKEN_FILE.tmp" 2>/dev/null || true
    chmod 0640 "$TOKEN_FILE.tmp" 2>/dev/null || true
    mv "$TOKEN_FILE.tmp" "$TOKEN_FILE"
fi

token=$(tr -d '\r\n' < "$TOKEN_FILE")
host=${HTTP_HOST:-localhost}
scheme=https
[[ "${HTTPS:-}" == "on" ]] || scheme=http

base_url="${scheme}://${host}/sub?token=${token}"

json_header
printf '{"ok":true,"token":"%s","base":"%s","formats":{"base64":"%s","text":"%s&fmt=text","singbox":"%s&fmt=singbox","clash":"%s&fmt=clash"}}\n' \
    "$token" "$base_url" "$base_url" "$base_url" "$base_url" "$base_url"
