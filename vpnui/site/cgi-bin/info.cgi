#!/var/tmp/vpnui/bin/busybox-mips ash
BB=/var/tmp/vpnui/bin/busybox-mips
BASE=/var/tmp/vpnui
ROOT=/var/tmp/vpnui/www
STORE=/var/LxC
NAMES=$STORE/device_names.txt
OUI=$ROOT/oui.txt
json_escape(){ echo "$1" | sed 's/\\/\\\\/g;s/"/\\"/g;s/	/ /g'; }
safe_mac(){ echo "$1" | tr 'A-F' 'a-f' | tr -cd '0-9a-f:'; }
# Vendor lookup by first 3 octets (XX:YY:ZZ) from $OUI.
vendor_for_mac(){
  [ -f "$OUI" ] || { echo ""; return; }
  pref=$(echo "$1" | tr '[:upper:]' '[:lower:]' | cut -c1-8)
  [ -z "$pref" ] && { echo ""; return; }
  grep -i "^${pref}:" "$OUI" 2>/dev/null | head -1 | cut -d':' -f4-
}
# Locally administered MAC = randomized (iPhone/Android privacy).
is_private_mac(){
  first=$(echo "$1" | cut -d: -f1 | tr '[:upper:]' '[:lower:]')
  low=$(echo "$first" | cut -c2)
  case "$low" in 2|3|6|7|a|b|e|f) return 0 ;; *) return 1 ;; esac
}
stat_field_for_mac(){
  file=$1
  mac=$(safe_mac "$2")
  field=$3
  [ -f "$file" ] || return 0
  [ -z "$mac" ] && return 0
  tr '[' '\n' < "$file" 2>/dev/null | awk -F'"' -v m="$mac" -v f="$field" 'tolower($4)==m {print $f; exit}'
}
firmware_hostname_for_mac(){
  mac=$(safe_mac "$1")
  [ -z "$mac" ] && return 0
  for item in \
    /www/js/common/wlan_client_stat.js:14 \
    /www/js/common/agent_client_wlan_stat.js:14 \
    /www/js/common/eth_client_stat.js:16 \
    /www/js/common/agent_client_eth_stat.js:16; do
    f=${item%:*}
    n=${item#*:}
    h=$(stat_field_for_mac "$f" "$mac" "$n")
    if [ -n "$h" ] && [ "$h" != "*" ] && [ "$h" != "-" ]; then
      echo "$h"
      return 0
    fi
  done
}
# Find hostname for MAC in whatever dhcp leases file the firmware uses.
hostname_for_mac(){
  mac=$(safe_mac "$1")
  [ -z "$mac" ] && return 0
  h=$(firmware_hostname_for_mac "$mac")
  if [ -n "$h" ]; then
    echo "$h"
    return 0
  fi
  for f in \
    /var/lib/misc/dnsmasq.leases \
    /tmp/dhcp.leases \
    /var/tmp/dhcp.leases \
    /var/run/dhcpd_br2.lease \
    /var/run/udhcpd.leases \
    /var/lib/dhcp/dhcpd.leases \
    /var/db/dhcp/dnsmasq.leases; do
    [ -f "$f" ] || continue
    h=$(awk -v m="$mac" 'tolower($2)==m {print $4; exit}' "$f" 2>/dev/null)
    [ -z "$h" ] && h=$(awk -v m="$mac" 'tolower($0) ~ m {for(i=1;i<=NF;i++) if($i=="client-hostname") {gsub(/[";]/,"",$(i+1)); print $(i+1); exit}}' "$f" 2>/dev/null)
    if [ -n "$h" ] && [ "$h" != "*" ]; then
      echo "$h"
      return 0
    fi
  done
}
# Manual override: MAC|name in /var/LxC/device_names.txt
name_for_mac(){
  mac=$(safe_mac "$1")
  [ -z "$mac" ] && return 0
  [ -f "$NAMES" ] || return 0
  awk -F'|' -v m="$mac" 'tolower($1)==m {print $2; exit}' "$NAMES" 2>/dev/null
}
uptime_s(){ cut -d ' ' -f 1 /proc/uptime | cut -d '.' -f 1; }
mem_total=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
mem_free=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
[ -z "$mem_free" ] && mem_free=$(awk '/MemFree/ {print $2}' /proc/meminfo)
load=$(cat /proc/loadavg | cut -d ' ' -f 1-3)
lxcline=$(df -k /var/LxC 2>/dev/null | awk 'NR==2 {print $2 "|" $3 "|" $4 "|" $5}')
tmp_line=$(df -k /var/tmp 2>/dev/null | awk 'NR==2 {print $2 "|" $3 "|" $4 "|" $5}')
vpn=false; ps | grep '[x]ray run' >/dev/null 2>&1 && vpn=true
httpd=false; ps | grep '[h]ttpd' >/dev/null 2>&1 && httpd=true
ftp=false; ps | grep '[t]cpsvd' >/dev/null 2>&1 && ftp=true
sftp=false; [ -x "$BASE/bin/sftp-server" ] && [ -f /etc/passwd ] && sftp=true
temp=""
for f in /sys/class/thermal/thermal_zone*/temp; do
  [ -f "$f" ] && temp=$(cat "$f" 2>/dev/null | head -1)
done
xray_version=""
xray_xhttp=false
if [ -x /var/tmp/xray ]; then
  xray_version=$(/var/tmp/xray version 2>/dev/null | sed -n '1p')
  echo "$xray_version" | grep -Eq '24\.|25\.|26\.' && xray_xhttp=true
fi
printf 'Content-Type: application/json; charset=utf-8\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'
echo "{"
echo "\"uptime\":$(uptime_s),\"load\":\"$(json_escape "$load")\",\"memTotal\":${mem_total:-0},\"memFree\":${mem_free:-0},\"temp\":\"$(json_escape "$temp")\","
echo "\"xrayVersion\":\"$(json_escape "$xray_version")\",\"xrayXhttp\":$xray_xhttp,"
echo "\"storage\":{\"lxc\":\"$(json_escape "$lxcline")\",\"tmp\":\"$(json_escape "$tmp_line")\"},"
echo "\"services\":{\"vpn\":$vpn,\"http\":$httpd,\"ftp\":$ftp,\"sftpPort\":$sftp},"
printf '"devices":['
awk -v oui="$OUI" -v names="$NAMES" '
BEGIN{
  while((getline ln < oui) > 0){
    n=split(ln,a,":")
    if(n<4) continue
    k=tolower(a[1]":"a[2]":"a[3])
    v=a[4]; for(i=5;i<=n;i++) v=v":"a[i]
    V[k]=v
  }
  close(oui)
  while((getline ln < names) > 0){
    p=index(ln,"|")
    if(p<=1) continue
    m=tolower(substr(ln,1,p-1))
    nm=substr(ln,p+1)
    N[m]=nm
  }
  close(names)
  first=1
}
NR==1 { next }
$4 == "00:00:00:00:00:00" { next }
{
  ip=$1; mac=tolower($4); dev=$6
  pref=substr(mac,1,8)
  vend = (pref in V) ? V[pref] : ""
  low=substr(mac,2,1)
  priv="false"
  if(low=="2"||low=="3"||low=="6"||low=="7"||low=="a"||low=="b"||low=="e"||low=="f") priv="true"
  type = (vend!="") ? vend : ((priv=="true") ? "Private MAC" : "Unknown")
  nm = (mac in N) ? N[mac] : ""
  gsub(/\\/,"\\\\",vend); gsub(/"/,"\\\"",vend)
  gsub(/\\/,"\\\\",type); gsub(/"/,"\\\"",type)
  gsub(/\\/,"\\\\",nm);   gsub(/"/,"\\\"",nm)
  sep = first ? "" : ","
  first=0
  printf "%s{\"ip\":\"%s\",\"mac\":\"%s\",\"iface\":\"%s\",\"type\":\"%s\",\"vendor\":\"%s\",\"private\":%s,\"hostname\":\"\",\"name\":\"%s\"}", sep, ip, mac, dev, type, vend, priv, nm
}
' /proc/net/arp
echo "]}"
