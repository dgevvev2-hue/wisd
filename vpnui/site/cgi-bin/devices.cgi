#!/var/tmp/vpnui/bin/busybox-mips ash
# LAN device name manager. Reads current MAC->hostname map from any
# dhcp leases file we can find and lets the operator set/unset a human
# friendly name override that is kept in /var/LxC so it survives reboot.
#
# State file:
#   /var/LxC/device_names.txt        one record per line: MAC|name
#   /var/LxC/vpn_clients.allow       one allowed VPN client IP per line
#   /var/LxC/vpn_clients.allowmac    one allowed VPN client MAC per line
#
# Actions:
#   list                             -> all known devices: ip/mac/iface/
#                                       vendor/hostname/name
#   rename  mac=XX:.. name=MyPhone   -> upsert override
#   forget  mac=XX:..                -> remove override
#   allow_vpn ip=192.168.0.X         -> allow this client through VPN
#   block_vpn ip=192.168.0.X         -> block this client from VPN
#
# Nothing destructive: no iptables, no service restart, just text files.

BASE=/var/tmp/vpnui
STORE=/var/LxC
NAMES=$STORE/device_names.txt
ALLOW=$STORE/vpn_clients.allow
ALLOW_MAC=$STORE/vpn_clients.allowmac
ACTION=list
MAC=
NAME=
IP=

urldecode(){ v=$(echo "$1" | sed 's/+/ /g;s/%/\\x/g'); printf '%b' "$v"; }
for p in $(echo "$QUERY_STRING" | tr '&' ' '); do
  k=${p%%=*}; v=${p#*=}; v=$(urldecode "$v")
  [ "$k" = "action" ] && ACTION=$v
  [ "$k" = "mac" ]    && MAC=$v
  [ "$k" = "name" ]   && NAME=$v
  [ "$k" = "ip" ]     && IP=$v
done

mkdir -p "$STORE"
touch "$NAMES" "$ALLOW" "$ALLOW_MAC"

safe_mac(){ echo "$1" | tr 'A-F' 'a-f' | tr -cd '0-9a-f:'; }
safe_name(){ echo "$1" | sed 's/[|"]/ /g;s/[\r\n]//g' | cut -c1-48; }
safe_ip(){ echo "$1" | tr -cd '0-9.'; }
json_escape(){ echo "$1" | sed 's/\\/\\\\/g;s/"/\\"/g;s/	/ /g'; }
valid_ip(){
  echo "$1" | awk -F. 'NF==4 {
    for (i=1; i<=4; i++) if ($i !~ /^[0-9]+$/ || $i < 0 || $i > 255) exit 1
    exit 0
  } { exit 1 }'
}
private_mac(){
  first=$(echo "$1" | cut -d: -f1 | tr 'A-F' 'a-f')
  case "$first" in
    02|06|0a|0e|12|16|1a|1e|22|26|2a|2e|32|36|3a|3e|42|46|4a|4e|52|56|5a|5e|62|66|6a|6e|72|76|7a|7e|82|86|8a|8e|92|96|9a|9e|a2|a6|aa|ae|b2|b6|ba|be|c2|c6|ca|ce|d2|d6|da|de|e2|e6|ea|ee|f2|f6|fa|fe) return 0 ;;
  esac
  return 1
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

firmware_iface_for_mac(){
  mac=$(safe_mac "$1")
  [ -z "$mac" ] && return 0
  for f in /www/js/common/wlan_client_stat.js /www/js/common/agent_client_wlan_stat.js; do
    cfg=$(stat_field_for_mac "$f" "$mac" 30)
    if [ -n "$cfg" ]; then
      ssid=$(echo "$cfg" | sed 's/.*WLANConfiguration\.//;s/[^0-9].*//')
      [ -n "$ssid" ] && { echo "SSID$ssid"; return 0; }
    fi
    iface=$(stat_field_for_mac "$f" "$mac" 22)
    [ -n "$iface" ] && { echo "$iface"; return 0; }
  done
  for f in /www/js/common/eth_client_stat.js /www/js/common/agent_client_eth_stat.js; do
    iface=$(stat_field_for_mac "$f" "$mac" 28)
    [ -n "$iface" ] && { echo "$iface"; return 0; }
  done
}

# Returns hostname for a MAC by scanning common dhcp leases paths.
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

# Returns manual override name for a MAC, if any.
name_for_mac(){
  mac=$(safe_mac "$1")
  [ -z "$mac" ] && return 0
  awk -F'|' -v m="$mac" 'tolower($1)==m {print $2; exit}' "$NAMES" 2>/dev/null
}

rename_mac(){
  mac=$(safe_mac "$1")
  name=$(safe_name "$2")
  [ -z "$mac" ] && return 1
  [ -z "$name" ] && return 1
  grep -vi "^$mac|" "$NAMES" > "$NAMES.tmp" 2>/dev/null
  echo "$mac|$name" >> "$NAMES.tmp"
  mv "$NAMES.tmp" "$NAMES"
}

forget_mac(){
  mac=$(safe_mac "$1")
  [ -z "$mac" ] && return 1
  grep -vi "^$mac|" "$NAMES" > "$NAMES.tmp" 2>/dev/null
  mv "$NAMES.tmp" "$NAMES"
}

vpn_allowed(){
  ip=$(safe_ip "$1")
  mac=$(safe_mac "$2")
  [ -n "$mac" ] && awk -v mac="$mac" '$0 == mac { found=1 } END { exit found ? 0 : 1 }' "$ALLOW_MAC" 2>/dev/null && return 0
  [ -n "$ip" ] && awk -v ip="$ip" '$0 == ip { found=1 } END { exit found ? 0 : 1 }' "$ALLOW" 2>/dev/null && return 0
  return 1
}

allow_vpn(){
  ip=$(safe_ip "$1")
  mac=$(safe_mac "$2")
  [ -n "$ip" ] && valid_ip "$ip" && awk -v ip="$ip" '$0 == ip { found=1 } END { exit found ? 0 : 1 }' "$ALLOW" 2>/dev/null || {
    [ -n "$ip" ] && valid_ip "$ip" && echo "$ip" >> "$ALLOW"
  }
  [ -n "$mac" ] && awk -v mac="$mac" '$0 == mac { found=1 } END { exit found ? 0 : 1 }' "$ALLOW_MAC" 2>/dev/null || {
    [ -n "$mac" ] && echo "$mac" >> "$ALLOW_MAC"
  }
}

block_vpn(){
  ip=$(safe_ip "$1")
  mac=$(safe_mac "$2")
  awk -v ip="$ip" '$0 != ip { print }' "$ALLOW" > "$ALLOW.tmp" 2>/dev/null
  mv "$ALLOW.tmp" "$ALLOW"
  awk -v mac="$mac" '$0 != mac { print }' "$ALLOW_MAC" > "$ALLOW_MAC.tmp" 2>/dev/null
  mv "$ALLOW_MAC.tmp" "$ALLOW_MAC"
}

sync_allowed_ips(){
  tmp="$ALLOW.tmp"
  : > "$tmp"
  [ -f "$ALLOW" ] && awk 'NF && $0 ~ /^192\.168\.0\.[0-9]{1,3}$/ && !seen[$0]++ { print }' "$ALLOW" >> "$tmp" 2>/dev/null
  awk 'NR>1 && $4!="00:00:00:00:00:00" {print $1 "|" tolower($4)}' /proc/net/arp 2>/dev/null | while IFS='|' read ip mac; do
    echo "$ip" | grep -Eq '^192\.168\.0\.[0-9]{1,3}$' || continue
    awk -v mac="$mac" '$0 == mac { found=1 } END { exit found ? 0 : 1 }' "$ALLOW_MAC" 2>/dev/null && echo "$ip" >> "$tmp"
  done
  awk 'NF && !seen[$0]++ { print }' "$tmp" > "$ALLOW" 2>/dev/null
  rm -f "$tmp"
}

restart_vpn_if_running(){
  ps | grep '[x]ray run' >/dev/null 2>&1 || return 0
  [ -x "$BASE/www/cgi-bin/vpn.cgi" ] || return 0
  QUERY_STRING="action=restart" "$BASE/www/cgi-bin/vpn.cgi" >/dev/null 2>&1
}

# JSON list of devices from ARP table, enriched with hostname + override.
emit_devices(){
  arpfile=$BASE/devices.arp
  jsonfile=$BASE/devices.jsonlines
  : > "$jsonfile"
  awk 'NR>1 && $4!="00:00:00:00:00:00" {
    mac=tolower($4)
    if (seen[mac]++) next
    print $1 "|" mac "|" $6
  }' /proc/net/arp > "$arpfile"
  while IFS='|' read ip mac dev; do
    [ -z "$ip" ] && continue
    host=$(hostname_for_mac "$mac")
    fwiface=$(firmware_iface_for_mac "$mac")
    [ -n "$fwiface" ] && dev=$fwiface
    over=$(name_for_mac "$mac")
    allowed=false; vpn_allowed "$ip" "$mac" && allowed=true
    vendor="Device"
    case "$mac" in
      94:bb:43*|94:e0:d6*) vendor="PC/Laptop" ;;
      68:4e:05*|3c:0b:4f*|94:87:e0*|ae:74:6d*|1a:98:bc*) vendor="Phone/Client" ;;
    esac
    private=false; private_mac "$mac" && private=true
    ipj=$(json_escape "$ip")
    macj=$(json_escape "$mac")
    devj=$(json_escape "$dev")
    hostj=$(json_escape "$host")
    overj=$(json_escape "$over")
    vendorj=$(json_escape "$vendor")
    printf '{"ip":"%s","mac":"%s","iface":"%s","type":"%s","vendor":"%s","hostname":"%s","name":"%s","private":%s,"vpnAllowed":%s}' \
      "$ipj" "$macj" "$devj" "$vendorj" "$vendorj" "$hostj" "$overj" "$private" "$allowed" >> "$jsonfile"
    echo >> "$jsonfile"
  done < "$arpfile"
  echo -n '['
  awk 'NF { if (n) printf ","; printf "%s", $0; n=1 }' "$jsonfile"
  echo -n ']'
}

printf 'Content-Type: application/json; charset=utf-8\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'

case "$ACTION" in
  rename)
    rename_mac "$MAC" "$NAME"
    ;;
  forget)
    forget_mac "$MAC"
    ;;
  allow_vpn)
    allow_vpn "$IP" "$MAC"
    sync_allowed_ips
    restart_vpn_if_running
    ;;
  block_vpn)
    block_vpn "$IP" "$MAC"
    sync_allowed_ips
    restart_vpn_if_running
    ;;
esac

sync_allowed_ips
echo -n '{"devices":'
emit_devices
echo '}'
