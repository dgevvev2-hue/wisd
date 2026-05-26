#!/bin/bash
# sub-rotate.cgi -- regenerate the subscription token. Called by the panel via
# POST /cgi-bin/sub-rotate.cgi (auth_request protected).
# Responds with {"ok":true,"token":"<new_token>"}.

set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib.sh"

TOKEN_FILE=$WISD_STATE_DIR/sub.token
new=$(head -c 32 /dev/urandom | xxd -p -c 64 | tr -d '\n')
printf '%s\n' "$new" > "$TOKEN_FILE.tmp"
chown wisd:wisd "$TOKEN_FILE.tmp" 2>/dev/null || true
chmod 0640 "$TOKEN_FILE.tmp" 2>/dev/null || true
mv "$TOKEN_FILE.tmp" "$TOKEN_FILE"

json_header
printf '{"ok":true,"token":"%s"}\n' "$new"
