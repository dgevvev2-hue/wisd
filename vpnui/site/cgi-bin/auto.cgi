#!/var/tmp/vpnui/bin/busybox-mips ash
BASE=/var/tmp/vpnui
ACTION=status
THRESHOLD=
INTERVAL=
urldecode(){ v=$(echo "$1" | sed 's/+/ /g;s/%/\\x/g'); printf '%b' "$v"; }
for p in $(echo "$QUERY_STRING" | tr '&' ' '); do
  k=${p%%=*}; v=${p#*=}; v=$(urldecode "$v")
  [ "$k" = "action" ] && ACTION=$v
  [ "$k" = "threshold" ] && THRESHOLD=$v
  [ "$k" = "interval" ] && INTERVAL=$v
done
safe_num(){ echo "$1" | tr -cd '0-9'; }
pid_running(){
  [ -f "$BASE/auto_switch.pid" ] || return 1
  pid=$(cat "$BASE/auto_switch.pid")
  [ -n "$pid" ] || return 1
  ps | grep "^[ ]*$pid " | grep -v grep >/dev/null 2>&1
}
print_status(){
  running=false; pid_running && running=true
  th=80; [ -f "$BASE/auto_threshold" ] && th=$(cat "$BASE/auto_threshold")
  iv=600; [ -f "$BASE/auto_interval" ] && iv=$(cat "$BASE/auto_interval")
  last=""; [ -f "$BASE/auto_status" ] && last=$(cat "$BASE/auto_status" | sed 's/"/\\"/g')
  echo "{\"running\":$running,\"threshold\":$th,\"interval\":$iv,\"last\":\"$last\"}"
}
mkdir -p "$BASE"
case "$ACTION" in
  start)
    th=$(safe_num "$THRESHOLD"); iv=$(safe_num "$INTERVAL")
    [ -z "$th" ] && th=80
    [ -z "$iv" ] && iv=600
    [ "$iv" -lt 60 ] && iv=60
    echo "$th" > "$BASE/auto_threshold"
    echo "$iv" > "$BASE/auto_interval"
    if ! pid_running; then
      /var/tmp/vpnui/auto_switch.sh >/var/tmp/vpnui/auto_switch.log 2>&1 &
      echo $! > "$BASE/auto_switch.pid"
    fi
    ;;
  stop)
    if [ -f "$BASE/auto_switch.pid" ]; then kill "$(cat "$BASE/auto_switch.pid")" 2>/dev/null; fi
    rm -f "$BASE/auto_switch.pid"
    ;;
  run)
    /var/tmp/vpnui/auto_check.sh >/var/tmp/vpnui/auto_switch.log 2>&1
    ;;
esac
printf 'Content-Type: application/json; charset=utf-8\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'
print_status
