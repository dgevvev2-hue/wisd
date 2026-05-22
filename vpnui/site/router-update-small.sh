#!/bin/sh
BB=/var/tmp/vpnui/bin/busybox-mips
[ -x "$BB" ] || BB=/var/usbmnt/sda1/vpnui/bin/busybox-mips
RAM=/var/tmp/vpnui/www
USB=/var/usbmnt/sda1/vpnui/www
URL=http://192.168.0.22:19778
mkdir -p "$RAM/cgi-bin" "$USB/cgi-bin" "$RAM/assets" "$USB/assets"
"$BB" wget -q -O /tmp/u_index.html "$URL/index.html" || exit 11
cp /tmp/u_index.html "$RAM/index.html"
cp /tmp/u_index.html "$USB/index.html"
"$BB" wget -q -O /tmp/u_ping.cgi "$URL/cgi-bin/ping.cgi" || exit 12
cp /tmp/u_ping.cgi "$RAM/cgi-bin/ping.cgi"
cp /tmp/u_ping.cgi "$USB/cgi-bin/ping.cgi"
"$BB" wget -q -O /tmp/u_vpn.cgi "$URL/cgi-bin/vpn.cgi" || exit 13
cp /tmp/u_vpn.cgi "$RAM/cgi-bin/vpn.cgi"
cp /tmp/u_vpn.cgi "$USB/cgi-bin/vpn.cgi"
"$BB" wget -q -O /tmp/u_devices.cgi "$URL/cgi-bin/devices.cgi" || exit 14
cp /tmp/u_devices.cgi "$RAM/cgi-bin/devices.cgi"
cp /tmp/u_devices.cgi "$USB/cgi-bin/devices.cgi"
"$BB" wget -q -O /tmp/u_icon.svg "$URL/assets/icon.svg" || exit 15
cp /tmp/u_icon.svg "$RAM/assets/icon.svg"
cp /tmp/u_icon.svg "$USB/assets/icon.svg"
chmod +x "$RAM"/cgi-bin/*.cgi "$USB"/cgi-bin/*.cgi 2>/dev/null
ps | grep 'busybox-mips httpd' | grep '192.168.0.1:8083' | grep -v grep | awk '{print $1}' > /tmp/httpd8083.pids
while read p; do [ -n "$p" ] && kill "$p" 2>/dev/null; done < /tmp/httpd8083.pids
sleep 1
"$BB" httpd -f -p 192.168.0.1:8083 -h "$RAM" >/var/tmp/vpnui/httpd.log 2>&1 &
echo UPLOAD_OK
