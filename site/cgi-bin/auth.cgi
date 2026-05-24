#!/bin/bash
# Internal endpoint used by nginx `auth_request`. Returns 200 if the
# wisd_sess cookie is valid, 401 otherwise. Body is empty either way.
#
# nginx config wires this to /__auth and copies HTTP_COOKIE through.

set -u

HERE=$(cd "$(dirname "$0")" && pwd)

if user=$(python3 "$HERE/wisd_auth.py" check_cookie "${HTTP_COOKIE-}" 2>/dev/null); then
    printf 'Status: 200 OK\r\n'
    printf 'X-Wisd-User: %s\r\n' "$user"
    printf 'Cache-Control: no-store\r\n'
    printf '\r\n'
    exit 0
fi

printf 'Status: 401 Unauthorized\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'
exit 0
