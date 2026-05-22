#!/var/tmp/vpnui/bin/busybox-mips ash
BB=/var/tmp/vpnui/bin/busybox-mips
ROOT=/var/tmp/vpnui/www
OUT=/var/tmp/vpnui/pings.json
HOST=
PORT=
ACTION=host
urldecode(){ v=$(echo "$1" | sed 's/+/ /g;s/%/\\x/g'); printf '%b' "$v"; }
for p in $(echo "$QUERY_STRING" | tr '&' ' '); do
  k=${p%%=*}; v=${p#*=}; v=$(urldecode "$v")
  [ "$k" = "action" ] && ACTION=$v
  [ "$k" = "host" ] && HOST=$v
  [ "$k" = "port" ] && PORT=$v
done
safe_host(){ echo "$1" | tr -cd 'A-Za-z0-9._:-'; }
safe_port(){
  p=$(echo "$1" | tr -cd '0-9')
  [ -z "$p" ] && p=443
  echo "$p"
}
uptime_cs(){ awk '{printf "%d", $1*100}' /proc/uptime 2>/dev/null; }
ping_ms(){
  safe=$(safe_host "$1")
  [ -z "$safe" ] && { echo null; return; }
  line=$($BB timeout -t 3 ping -c 1 "$safe" 2>/dev/null | grep 'time=' | head -1)
  ms=$(echo "$line" | sed -n 's/.*time=\([0-9.]*\).*/\1/p')
  [ -z "$ms" ] && ms=null
  echo "$ms"
}
tcp_ms(){
  safe=$(safe_host "$1")
  port=$(safe_port "$2")
  [ -z "$safe" ] && { echo null; return; }
  a=$(uptime_cs)
  $BB timeout -t 3 "$BB" nc -z -w 2 "$safe" "$port" >/dev/null 2>&1
  rc=$?
  b=$(uptime_cs)
  [ "$rc" = 0 ] || { echo null; return; }
  [ -z "$a" ] && { echo 0; return; }
  [ -z "$b" ] && { echo 0; return; }
  awk -v a="$a" -v b="$b" 'BEGIN { d=(b-a)*10; if (d<1) d=1; printf "%.1f", d }'
}
node_port(){
  id="$1"
  [ -f "$ROOT/configs/$id.json" ] || { echo 443; return; }
  p=$(sed -n 's/.*"port"[ ]*:[ ]*\([0-9][0-9]*\).*/\1/p' "$ROOT/configs/$id.json" | head -1)
  [ -z "$p" ] && p=443
  echo "$p"
}
best_ms(){
  h=$(safe_host "$1")
  p=$(safe_port "$2")
  ms=$(ping_ms "$h")
  [ "$ms" != "null" ] && { echo "$ms"; return; }
  tcp_ms "$h" "$p"
}
printf 'Content-Type: application/json; charset=utf-8\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'
if [ -n "$HOST" ] && [ "$ACTION" != "all" ]; then
  safe=$(safe_host "$HOST")
  port=$(safe_port "$PORT")
  avg=$(best_ms "$safe" "$port")
  echo "{\"host\":\"$safe\",\"ping\":$avg}"
  exit 0
fi
echo -n '{"pings":{' > "$OUT"
first=1
if [ -s "$ROOT/nodes.txt" ]; then
  while IFS='|' read id name host old ips; do
    [ -z "$id" ] && continue
    port=$(node_port "$id")
    ms=$(best_ms "$host" "$port")
    [ "$first" = 0 ] && echo -n ',' >> "$OUT"
    first=0
    echo -n "\"$id\":$ms" >> "$OUT"
  done < "$ROOT/nodes.txt"
elif [ -s "$ROOT/nodes.json" ]; then
  id=
  while IFS= read line; do
    case "$line" in
      *'"id"'*) id=$(echo "$line" | sed -n 's/.*"id"[ ]*:[ ]*\([0-9][0-9]*\).*/\1/p') ;;
      *'"host"'*)
        host=$(echo "$line" | sed -n 's/.*"host"[ ]*:[ ]*"\([^"]*\)".*/\1/p')
        [ -z "$id" ] && continue
        port=$(node_port "$id")
        ms=$(best_ms "$host" "$port")
        [ "$first" = 0 ] && echo -n ',' >> "$OUT"
        first=0
        echo -n "\"$id\":$ms" >> "$OUT"
        id=
        ;;
    esac
  done < "$ROOT/nodes.json"
fi
echo '}}' >> "$OUT"
cat "$OUT"
