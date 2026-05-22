#!/var/tmp/vpnui/bin/busybox-mips ash
BB=/var/tmp/vpnui/bin/busybox-mips
BASE=/var/tmp/vpnui
ROOT=$BASE/www
USB=/var/usbmnt/sda1/vpnui
ACTION=status

urldecode(){ v=$(echo "$1" | sed 's/+/ /g;s/%/\\x/g'); printf '%b' "$v"; }
for p in $(echo "$QUERY_STRING" | tr '&' ' '); do
  k=${p%%=*}; v=${p#*=}; v=$(urldecode "$v")
  [ "$k" = "action" ] && ACTION=$v
done

json_escape(){ echo "$1" | sed 's/\\/\\\\/g;s/"/\\"/g;s/	/ /g'; }
uptime_s(){ cut -d ' ' -f 1 /proc/uptime | cut -d '.' -f 1; }
httpd_running(){ ps | grep '/var/tmp/vpnui/bin/busybox-mips httpd' | grep -v grep >/dev/null 2>&1; }
stop_httpd(){
  ps | grep '/var/tmp/vpnui/bin/busybox-mips httpd' | grep -v grep | awk '{print $1}' | while read pid; do kill -9 "$pid" 2>/dev/null; done
}
start_httpd(){
  "$BB" httpd -f -p 192.168.0.1:8083 -h "$ROOT" > "$BASE/httpd.log" 2>&1 &
}
restart_httpd(){
  stop_httpd
  start_httpd
}
ram_ready(){ [ -f "$ROOT/index.html" ] && [ -x "$BB" ]; }
usb_ready(){ [ -d "$USB/www" ] && [ -x "$USB/bin/busybox-mips" ]; }
mount_usb(){
  [ -d /var/usbmnt/sda1 ] || mkdir -p /var/usbmnt/sda1
  mount | grep '/var/usbmnt/sda1' >/dev/null 2>&1 && return 0
  mount -t ext2 /dev/sda1 /var/usbmnt/sda1 2>/dev/null || return 1
}
start_ram(){
  mount_usb 2>/dev/null
  mkdir -p "$BASE/bin" "$ROOT"
  if [ -d "$USB/www" ]; then
    rm -rf "$ROOT"
    mkdir -p "$ROOT"
    cp -a "$USB/www/." "$ROOT/" 2>/dev/null
  fi
  [ -x "$BB" ] || cp "$USB/bin/busybox-mips" "$BB" 2>/dev/null
  [ -x "$BASE/bin/rwget" ] || cp "$USB/bin/rwget" "$BASE/bin/rwget" 2>/dev/null
  [ -x /var/tmp/xray ] || cp "$USB/xray" /var/tmp/xray 2>/dev/null
  chmod +x "$BASE/bin/"* /var/tmp/xray "$ROOT/cgi-bin/"*.cgi 2>/dev/null
  restart_httpd
  iptables -C INPUT -i br2 -p tcp --dport 8083 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -i br2 -p tcp --dport 8083 -j ACCEPT
}
status_json(){
  http=false; httpd_running && http=true
  ram=false; ram_ready && ram=true
  usb=false; usb_ready && usb=true
  up=$(uptime_s)
  boot=""; [ -r /proc/stat ] && boot=$(awk '/^btime /{print $2}' /proc/stat)
  tmp=$(df -k /var/tmp 2>/dev/null | awk 'NR==2 {print $2 "|" $3 "|" $4 "|" $5}')
  usbl=$(df -k /var/usbmnt/sda1 2>/dev/null | awk 'NR==2 {print $2 "|" $3 "|" $4 "|" $5}')
  echo "{\"ok\":true,\"httpd\":$http,\"ramReady\":$ram,\"usbReady\":$usb,\"uptime\":$up,\"boot\":\"$(json_escape "$boot")\",\"tmp\":\"$(json_escape "$tmp")\",\"usb\":\"$(json_escape "$usbl")\"}"
}

printf 'Content-Type: application/json; charset=utf-8\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'
case "$ACTION" in
  ram)
    start_ram
    sleep 1
    status_json
    ;;
  httpd)
    restart_httpd
    sleep 1
    status_json
    ;;
  reboot)
    (sleep 1; reboot) >/dev/null 2>&1 &
    echo '{"ok":true,"message":"rebooting"}'
    ;;
  status|*)
    status_json
    ;;
esac
