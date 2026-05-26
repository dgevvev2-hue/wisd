#!/bin/bash
# Clears the wisd_sess cookie. No body, no auth required.
set -u

printf 'Status: 200 OK\r\n'
printf 'Set-Cookie: wisd_sess=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax\r\n'
printf 'Content-Type: application/json; charset=utf-8\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'
printf '{"ok":true}\n'
exit 0
