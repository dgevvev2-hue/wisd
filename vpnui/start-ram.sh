#!/bin/sh
USB=/var/usbmnt/sda1
APP=/var/tmp/vpnui

[ -d "$USB/vpnui" ] || exit 1

for p in `ps | grep '/var/tmp/vpnui/bin/busybox-mips httpd' | grep -v grep | awk '{print $1}'`; do
  kill -9 "$p" 2>/dev/null
done
for p in `ps | grep '/var/tmp/vpnui/bin/busybox-mips tcpsvd' | grep -v grep | awk '{print $1}'`; do
  kill -9 "$p" 2>/dev/null
done
sleep 1

mkdir -p "$APP/bin" "$APP/www"
cp "$USB/vpnui/bin/busybox-mips" "$APP/bin/busybox-mips"
cp "$USB/vpnui/bin/sftp-server" "$APP/bin/sftp-server" 2>/dev/null
[ -x /var/tmp/xray ] || cp "$USB/vpnui/xray" /var/tmp/xray
cp "$USB/vpnui/geoip.dat" "$APP/geoip.dat" 2>/dev/null
cp "$USB/vpnui/geosite.dat" "$APP/geosite.dat" 2>/dev/null

rm -rf "$APP/www"
mkdir -p "$APP/www"
cp -a "$USB/vpnui/www/." "$APP/www/"
cp "$USB/vpnui/auto_check.sh" "$APP/auto_check.sh" 2>/dev/null
cp "$USB/vpnui/auto_switch.sh" "$APP/auto_switch.sh" 2>/dev/null

chmod +x "$APP/bin/"* /var/tmp/xray "$APP"/www/cgi-bin/*.cgi "$APP"/auto_*.sh 2>/dev/null

"$APP/bin/busybox-mips" httpd -f -p 192.168.0.1:8083 -h "$APP/www" >"$APP/httpd.log" 2>&1 &
"$APP/bin/busybox-mips" tcpsvd -E 192.168.0.1 2121 "$APP/bin/busybox-mips" ftpd -w / >"$APP/ftpd.log" 2>&1 &

iptables -I INPUT 1 -i br2 -p tcp --dport 8083 -j ACCEPT 2>/dev/null
iptables -I INPUT 1 -i br2 -p tcp --dport 2121 -j ACCEPT 2>/dev/null

[ -x /var/LxC/dns-protect.sh ] && /var/LxC/dns-protect.sh

if [ -f /var/LxC/vpnui.autostart ]; then
  VID=`cat /var/LxC/vpnui.state 2>/dev/null`
  VMODE=`cat /var/LxC/vpnui.mode 2>/dev/null`
  [ -z "$VID" ] && VID=4
  [ -z "$VMODE" ] && VMODE=tunnel
  QUERY_STRING="action=connect&id=$VID&mode=$VMODE" "$APP/www/cgi-bin/vpn.cgi" >/var/tmp/vpnui/autostart.log 2>&1
fi

[ -x /var/LxC/vpnui-watchdog.sh ] && /var/LxC/vpnui-watchdog.sh start
[ -x /var/LxC/tgbot/router-tgbot.sh ] && /var/LxC/tgbot/router-tgbot.sh start >/dev/null 2>&1
