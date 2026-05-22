#!/var/tmp/vpnui/bin/busybox-mips ash
BASE=/var/tmp/vpnui
ROOT=/var/tmp/vpnui/www
THRESHOLD=80
[ -f "$BASE/auto_threshold" ] && THRESHOLD=$(cat "$BASE/auto_threshold")
MODE=tunnel
[ -f "$BASE/mode" ] && MODE=$(cat "$BASE/mode")
CUR=""
[ -f "$BASE/state" ] && CUR=$(cat "$BASE/state")
now(){ cut -d ' ' -f 1 /proc/uptime | cut -d '.' -f 1; }
ping_ms(){
  h="$1"
  line=$(ping -c 1 -W 1 "$h" 2>/dev/null | grep 'time=' | head -1)
  echo "$line" | sed -n 's/.*time=\([0-9.]*\).*/\1/p' | cut -d '.' -f 1
}
best_id=""
best_ms=99999
cur_ms=99999
while IFS='|' read id name host old ips; do
  [ -z "$id" ] && continue
  ms=$(ping_ms "$host")
  [ -z "$ms" ] && ms=99999
  [ "$id" = "$CUR" ] && cur_ms=$ms
  if [ "$ms" -lt "$best_ms" ]; then best_ms=$ms; best_id=$id; fi
done < "$ROOT/nodes.txt"
msg="checked current=$CUR current_ms=$cur_ms best=$best_id best_ms=$best_ms threshold=$THRESHOLD"
if [ -n "$best_id" ] && [ "$best_ms" -lt 99999 ]; then
  if [ "$CUR" != "$best_id" ] && { [ "$cur_ms" -gt "$THRESHOLD" ] || [ "$cur_ms" -ge 99999 ]; }; then
    /var/tmp/vpnui/bin/busybox-mips wget -q -O - "http://192.168.0.1:8083/cgi-bin/vpn.cgi?action=connect&id=$best_id&mode=$MODE" >/dev/null 2>&1
    msg="switched from=$CUR current_ms=$cur_ms to=$best_id best_ms=$best_ms threshold=$THRESHOLD"
  fi
fi
echo "$(now) $msg" > "$BASE/auto_status"
echo "$msg"
