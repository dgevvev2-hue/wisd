#!/bin/bash
# Common helpers for wisd CGI scripts.
#
# All paths and constants live here so individual CGI scripts can be very thin.

set -u

WISD_STATE_DIR=${WISD_STATE_DIR:-/var/lib/wisd}
WISD_CONF_DIR=${WISD_CONF_DIR:-/etc/wisd}
WISD_LOG_DIR=${WISD_LOG_DIR:-/var/log/wisd}
WISD_SUB_DIR=$WISD_STATE_DIR/subscriptions
WISD_NODES_FILE=$WISD_STATE_DIR/nodes.json
WISD_STATE_FILE=$WISD_STATE_DIR/state
WISD_MODE_FILE=$WISD_STATE_DIR/mode
WISD_NODE_FILE=$WISD_STATE_DIR/selected_node
WISD_STARTED_FILE=$WISD_STATE_DIR/started_at
WISD_RULES_FILE=$WISD_STATE_DIR/rules.json
WISD_SERVER_FILE=$WISD_STATE_DIR/server.json
WISD_XRAY_CONFIG=${WISD_XRAY_CONFIG:-$WISD_STATE_DIR/xray.json}
WISD_XRAY_SERVICE=${WISD_XRAY_SERVICE:-wisd-xray.service}
WISD_SUDO=${WISD_SUDO:-sudo}

mkdir -p "$WISD_STATE_DIR" "$WISD_SUB_DIR" "$WISD_LOG_DIR" 2>/dev/null || true

# json_escape <string>  -- writes JSON-escaped string (no surrounding quotes)
json_escape() {
    local s=${1-}
    # Replace in order: backslash, quote, then control chars commonly seen.
    s=${s//\\/\\\\}
    s=${s//\"/\\\"}
    s=${s//$'\n'/\\n}
    s=${s//$'\r'/\\r}
    s=${s//$'\t'/\\t}
    printf '%s' "$s"
}

# urldecode <s>  -- writes decoded string
urldecode() {
    local s=${1//+/ }
    printf '%b' "${s//%/\\x}"
}

# parse_query  -- fills QPARAM_<key> bash variables from $QUERY_STRING
declare -A QPARAM
parse_query() {
    local q=${QUERY_STRING-}
    QPARAM=()
    [[ -z "$q" ]] && return 0
    local IFS='&'
    local p
    for p in $q; do
        local k=${p%%=*}
        local v=${p#*=}
        [[ "$k" == "$p" ]] && v=""
        QPARAM["$k"]=$(urldecode "$v")
    done
}

# read_post_body  -- reads CONTENT_LENGTH bytes from stdin into $POST_BODY
POST_BODY=""
read_post_body() {
    local cl=${CONTENT_LENGTH:-0}
    POST_BODY=""
    if [[ "$cl" =~ ^[0-9]+$ ]] && (( cl > 0 )); then
        if (( cl > 4194304 )); then
            cl=4194304
        fi
        POST_BODY=$(head -c "$cl")
    fi
}

# json_header  -- print HTTP headers for JSON response
json_header() {
    printf 'Content-Type: application/json; charset=utf-8\r\n'
    printf 'Cache-Control: no-store\r\n'
    printf 'Access-Control-Allow-Origin: *\r\n'
    printf '\r\n'
}

# json_error <code> <message>
json_error() {
    json_header
    printf '{"ok":false,"code":%s,"message":"%s"}\n' "${1-1}" "$(json_escape "${2-error}")"
    exit 0
}

# json_ok <inner JSON without braces>
json_ok() {
    json_header
    if [[ -n "${1-}" ]]; then
        printf '{"ok":true,%s}\n' "$1"
    else
        printf '{"ok":true}\n'
    fi
    exit 0
}

# xray_running -- 0 if running, 1 if not
xray_running() {
    pgrep -x xray >/dev/null 2>&1
}

# service_call <cmd>   -- run systemctl on wisd-xray.service via sudo
service_call() {
    $WISD_SUDO systemctl "$1" "$WISD_XRAY_SERVICE" >/dev/null 2>&1
}

# uuid_gen
uuid_gen() {
    cat /proc/sys/kernel/random/uuid 2>/dev/null || \
        python3 -c 'import uuid; print(uuid.uuid4())'
}

# random_hex <bytes>
random_hex() {
    local n=${1:-8}
    head -c "$n" /dev/urandom | xxd -p -c 256
}

# uptime_now
uptime_now() {
    local raw
    raw=$(cut -d ' ' -f 1 /proc/uptime)
    printf '%d' "${raw%.*}"
}

# require_jq  -- bail out if jq missing
require_jq() {
    command -v jq >/dev/null 2>&1 || json_error 50 "jq is required on server"
}

# slugify <s>
slugify() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9._-]\+/-/g; s/^-//; s/-$//'
}

# notify the xray manager to regenerate config.
regen_xray() {
    $WISD_SUDO "$WISD_CONF_DIR/regen.sh" "$@"
}
