#!/var/tmp/vpnui/bin/busybox-mips ash
set -u
BASE_URL="${1:-http://192.168.0.22:8008}"
BB=/var/tmp/vpnui/bin/busybox-mips
RAM=/var/tmp/vpnui/www
USB=/var/usbmnt/sda1/vpnui/www
TRAM=/var/tmp/vpnui/traffic/www
TUSB=/var/usbmnt/sda1/vpnui/traffic/www

fetch_one(){
  rel="$1"
  for root in "$RAM" "$USB"; do
    mkdir -p "$root/$(dirname "$rel")" 2>/dev/null
    "$BB" wget -q -O "$root/$rel" "$BASE_URL/$rel" 2>/dev/null || /var/tmp/vpnui/bin/rwget "$BASE_URL/$rel" "$root/$rel" 2>/dev/null || return 1
  done
}

fetch_one index.html || exit 10
fetch_one traffic.html || exit 11
fetch_one cgi-bin/vpn.cgi || exit 12
fetch_one cgi-bin/selective.cgi || exit 13
fetch_one cgi-bin/traffic.cgi || exit 14
fetch_one cgi-bin/subscription.cgi || exit 15

fetch_traffic(){
  src="$1"
  dst="$2"
  for root in "$TRAM" "$TUSB"; do
    mkdir -p "$root/$(dirname "$dst")" 2>/dev/null
    "$BB" wget -q -O "$root/$dst" "$BASE_URL/$src" 2>/dev/null || /var/tmp/vpnui/bin/rwget "$BASE_URL/$src" "$root/$dst" 2>/dev/null || return 1
  done
}

fetch_traffic traffic/index.html index.html || exit 20
fetch_traffic traffic/style.css style.css || exit 21
fetch_traffic traffic/script.js script.js || exit 22
fetch_traffic cgi-bin/traffic.cgi cgi-bin/traffic.cgi || exit 23
fetch_traffic assets/icon.svg assets/icon.svg || exit 24

chmod +x "$RAM"/cgi-bin/*.cgi "$USB"/cgi-bin/*.cgi "$TRAM"/cgi-bin/*.cgi "$TUSB"/cgi-bin/*.cgi 2>/dev/null

while ps | grep '[h]ttpd -f -p 192.168.0.1:8083' >/dev/null 2>&1; do
  pid=$(ps | grep '[h]ttpd -f -p 192.168.0.1:8083' | awk 'NR==1{print $1}')
  [ -z "$pid" ] && break
  kill "$pid" 2>/dev/null || break
  sleep 1
done

"$BB" httpd -f -p 192.168.0.1:8083 -h "$RAM" >/var/tmp/vpnui/httpd.log 2>&1 &

while ps | grep '[h]ttpd -f -p 192.168.0.1:8084' >/dev/null 2>&1; do
  pid=$(ps | grep '[h]ttpd -f -p 192.168.0.1:8084' | awk 'NR==1{print $1}')
  [ -z "$pid" ] && break
  kill "$pid" 2>/dev/null || break
  sleep 1
done

"$BB" httpd -f -p 192.168.0.1:8084 -h "$TRAM" >/var/tmp/vpnui/traffic-httpd.log 2>&1 &
iptables -C INPUT -p tcp --dport 8084 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport 8084 -j ACCEPT 2>/dev/null
iptables -C INPUT -i br2 -p tcp --dport 8084 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -i br2 -p tcp --dport 8084 -j ACCEPT 2>/dev/null
echo ok
