#!/var/tmp/vpnui/bin/busybox-mips ash
BASE=/var/tmp/vpnui
while true; do
  /var/tmp/vpnui/auto_check.sh
  INTERVAL=600
  [ -f "$BASE/auto_interval" ] && INTERVAL=$(cat "$BASE/auto_interval")
  [ "$INTERVAL" -lt 60 ] && INTERVAL=60
  sleep "$INTERVAL"
done
