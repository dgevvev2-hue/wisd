#!/bin/bash
# traffic.cgi -- last N lines of xray log (lightweight, no Stats API setup needed).
DIR=$(dirname "$0")
. "$DIR/lib.sh"

parse_query
ACTION=${QPARAM[action]:-stats}
NLINES=${QPARAM[lines]:-50}
[[ "$NLINES" =~ ^[0-9]+$ ]] || NLINES=50
(( NLINES > 2000 )) && NLINES=2000

json_header

case "$ACTION" in
    log)
        # raw last lines of error log
        if [[ -f "$WISD_LOG_DIR/xray.log" ]]; then
            lines=$(tail -n "$NLINES" "$WISD_LOG_DIR/xray.log")
        else
            lines=""
        fi
        # Emit as JSON string.
        python3 -c "import json,sys; print(json.dumps({'ok': True, 'log': sys.stdin.read()}, ensure_ascii=False))" <<<"$lines"
        ;;
    stats|*)
        # Try to read /proc/<pid>/net/dev to see bytes in/out.
        pid=$(pgrep -x xray | head -1)
        rx=0; tx=0
        if [[ -n "$pid" && -r "/proc/$pid/net/dev" ]]; then
            # iface eth0 / ens*: pick first non-loopback
            line=$(awk '
                NR>2 && $1 != "lo:" {gsub(":","",$1); print $1" "$2" "$10; exit}
            ' "/proc/$pid/net/dev")
            if [[ -n "$line" ]]; then
                rx=$(awk '{print $2}' <<<"$line")
                tx=$(awk '{print $3}' <<<"$line")
            fi
        fi
        # connections
        conn=$(ss -tn state established 2>/dev/null | wc -l)
        (( conn > 0 )) && conn=$(( conn - 1 ))  # subtract header
        cat <<JSON
{
  "ok": true,
  "rxBytes": ${rx:-0},
  "txBytes": ${tx:-0},
  "connections": ${conn:-0}
}
JSON
        ;;
esac
