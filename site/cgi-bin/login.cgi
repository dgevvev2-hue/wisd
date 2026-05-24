#!/bin/bash
# POST /cgi-bin/login.cgi  --  body: user=...&pass=...
#
# On success: sets HttpOnly Secure SameSite=Lax cookie wisd_sess=<token>
#             and replies {"ok":true}.
# On failure: replies 401 {"ok":false, "code":401, "message":"..."} with
#             a small artificial delay to slow down brute force.

set -u

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib.sh"

ADMIN_FILE=$WISD_STATE_DIR/admin.json

# Read body once.
read_post_body

# Parse application/x-www-form-urlencoded body (user, pass).
post_user=""
post_pass=""
if [[ -n "$POST_BODY" ]]; then
    IFS='&' read -ra parts <<<"$POST_BODY"
    for p in "${parts[@]}"; do
        k=${p%%=*}
        v=${p#*=}
        [[ "$k" == "$p" ]] && v=""
        case "$k" in
            user) post_user=$(urldecode "$v") ;;
            pass) post_pass=$(urldecode "$v") ;;
        esac
    done
fi

# Slight delay on any attempt — cheap throttling.
sleep 0.4 2>/dev/null || true

if [[ ! -s "$ADMIN_FILE" ]]; then
    json_header
    printf 'Status: 500 Internal Server Error\r\n'
    printf '{"ok":false,"code":500,"message":"admin.json missing on server"}\n'
    exit 0
fi

admin_user=$(jq -r '.user // ""' "$ADMIN_FILE")
admin_hash=$(jq -r '.passHash // ""' "$ADMIN_FILE")

if [[ -z "$post_user" || -z "$post_pass" || -z "$admin_user" || -z "$admin_hash" ]]; then
    printf 'Status: 401 Unauthorized\r\n'
    json_header
    printf '{"ok":false,"code":401,"message":"missing credentials"}\n'
    exit 0
fi

if [[ "$post_user" != "$admin_user" ]]; then
    printf 'Status: 401 Unauthorized\r\n'
    json_header
    printf '{"ok":false,"code":401,"message":"invalid credentials"}\n'
    exit 0
fi

if ! python3 "$HERE/wisd_auth.py" verify "$admin_hash" "$post_pass" 2>/dev/null; then
    printf 'Status: 401 Unauthorized\r\n'
    json_header
    printf '{"ok":false,"code":401,"message":"invalid credentials"}\n'
    exit 0
fi

token=$(python3 "$HERE/wisd_auth.py" issue "$admin_user" 2>/dev/null)
if [[ -z "$token" ]]; then
    printf 'Status: 500 Internal Server Error\r\n'
    json_header
    printf '{"ok":false,"code":500,"message":"could not issue session token"}\n'
    exit 0
fi

# Cookie attributes:
#   HttpOnly      — JS can't read it (XSS protection)
#   Secure        — only sent over HTTPS (auto-omitted if served over HTTP for local dev)
#   SameSite=Lax  — sent on top-level nav, not on cross-site POST
#   Max-Age       — 15 days
#   Path=/        — applies to whole site
secure_attr=""
if [[ "${HTTPS:-}" == "on" ]] || [[ "${HTTP_X_FORWARDED_PROTO:-}" == "https" ]]; then
    secure_attr="; Secure"
fi

printf 'Status: 200 OK\r\n'
printf 'Set-Cookie: wisd_sess=%s; Path=/; Max-Age=1296000; HttpOnly; SameSite=Lax%s\r\n' "$token" "$secure_attr"
json_header
printf '{"ok":true,"user":"%s"}\n' "$(json_escape "$admin_user")"
exit 0
