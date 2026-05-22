#!/var/tmp/vpnui/bin/busybox-mips ash
BB=/var/tmp/vpnui/bin/busybox-mips
BASE=/var/tmp/vpnui
STORE=/var/LxC
LOG=$BASE/xray.log
ACCESS=$BASE/xray.access.log
NAMES=$STORE/device_names.txt
STATE=$STORE/traffic.state
CHAIN=VPNUI_TRAFFIC
ACTION=status

urldecode(){ v=$(echo "$1" | sed 's/+/ /g;s/%/\\x/g'); printf '%b' "$v"; }
for p in $(echo "$QUERY_STRING" | tr '&' ' '); do
  k=${p%%=*}; v=${p#*=}; v=$(urldecode "$v")
  [ "$k" = "action" ] && ACTION=$v
done

mkdir -p "$STORE"
touch "$NAMES" "$STATE"

json_escape(){ echo "$1" | sed 's/\\/\\\\/g;s/"/\\"/g;s/	/ /g'; }
safe_mac(){ echo "$1" | tr 'A-F' 'a-f' | tr -cd '0-9a-f:'; }
uptime_now(){ cut -d ' ' -f 1 /proc/uptime | cut -d '.' -f 1; }

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

name_for_mac(){
  mac=$(safe_mac "$1")
  [ -z "$mac" ] && return 0
  awk -F'|' -v m="$mac" 'tolower($1)==m {print $2; exit}' "$NAMES" 2>/dev/null
}

ensure_chain(){
  iptables -N "$CHAIN" 2>/dev/null
  iptables -C FORWARD -j "$CHAIN" 2>/dev/null || iptables -I FORWARD 1 -j "$CHAIN" 2>/dev/null
  awk 'NR>1 && $4!="00:00:00:00:00:00" && index($1,"192.168.0.")==1 {print $1}' /proc/net/arp 2>/dev/null | while read ip; do
    [ -z "$ip" ] && continue
    iptables -C "$CHAIN" -s "$ip" -j RETURN 2>/dev/null || iptables -A "$CHAIN" -s "$ip" -j RETURN 2>/dev/null
    iptables -C "$CHAIN" -d "$ip" -j RETURN 2>/dev/null || iptables -A "$CHAIN" -d "$ip" -j RETURN 2>/dev/null
  done
}

snapshot_counters(){
  out=$BASE/traffic.counters
  : > "$out"
  iptables -L "$CHAIN" -vnx 2>/dev/null | awk '
    $3=="RETURN" {
      bytes=$2; src=$8; dst=$9
      if (index(src,"192.168.0.")==1) tx[src]+=bytes
      if (index(dst,"192.168.0.")==1) rx[dst]+=bytes
    }
    END {
      for (ip in rx) seen[ip]=1
      for (ip in tx) seen[ip]=1
      for (ip in seen) print ip "|" (rx[ip]+0) "|" (tx[ip]+0)
    }
  ' > "$out"
}

counter_for(){
  ip="$1"
  awk -F'|' -v ip="$ip" '$1==ip {print $2 "|" $3; found=1} END{if(!found) print "0|0"}' "$BASE/traffic.counters" 2>/dev/null
}

old_for(){
  ip="$1"
  awk -F'|' -v ip="$ip" '$1==ip {print $2 "|" $3 "|" $4; found=1} END{if(!found) print "0|0|0"}' "$STATE" 2>/dev/null
}

emit_devices(){
  now=$(uptime_now)
  next=$BASE/traffic.state.next
  : > "$next"
  first=1
  echo -n '['
  awk 'NR>1 && $4!="00:00:00:00:00:00" && index($1,"192.168.0.")==1 {
    mac=tolower($4)
    if (seen[mac]++) next
    print $1 "|" mac "|" $6
  }' /proc/net/arp 2>/dev/null | while IFS='|' read ip mac iface; do
    [ -z "$ip" ] && continue
    fwiface=$(firmware_iface_for_mac "$mac")
    [ -n "$fwiface" ] && iface=$fwiface
    host=$(firmware_hostname_for_mac "$mac")
    manual=$(name_for_mac "$mac")
    title="$manual"; [ -z "$title" ] && title="$host"; [ -z "$title" ] && title="Client ${ip##*.}"
    cur=$(counter_for "$ip")
    rx=${cur%|*}; tx=${cur#*|}
    old=$(old_for "$ip")
    orx=$(echo "$old" | cut -d'|' -f1)
    otx=$(echo "$old" | cut -d'|' -f2)
    ots=$(echo "$old" | cut -d'|' -f3)
    dt=$((now-ots)); [ "$dt" -le 0 ] && dt=1
    drx=$((rx-orx)); [ "$drx" -lt 0 ] && drx=0
    dtx=$((tx-otx)); [ "$dtx" -lt 0 ] && dtx=0
    rxps=$((drx/dt)); txps=$((dtx/dt))
    echo "$ip|$rx|$tx|$now" >> "$next"
    [ "$first" = 0 ] && echo -n ','
    first=0
    printf '{"ip":"%s","mac":"%s","name":"%s","hostname":"%s","iface":"%s","rx":%s,"tx":%s,"rxps":%s,"txps":%s}' \
      "$(json_escape "$ip")" "$(json_escape "$mac")" "$(json_escape "$title")" "$(json_escape "$host")" "$(json_escape "$iface")" "$rx" "$tx" "$rxps" "$txps"
  done
  echo -n ']'
  mv "$next" "$STATE" 2>/dev/null
}

collect_domains(){
  tmp=$BASE/traffic.events
  : > "$tmp"
  if [ -f "$LOG" ]; then
    $BB tail -500 "$LOG" | $BB awk '
      function idof(line){ if (match(line, /\[[0-9]+\]/)) return substr(line, RSTART+1, RLENGTH-2); return ""; }
      function clean(v){ sub(/^tcp:/,"",v); sub(/^udp:/,"",v); sub(/:[0-9]+$/,"",v); gsub(/[\r\n]/,"",v); return v; }
      {
        id=idof($0); if (id == "") next;
        if ($0 ~ /received request for/) { src=$NF; sub(/:[0-9]+$/,"",src); s[id]=src; next; }
        if ($0 ~ /sniffed domain:/) { d=$NF; d=clean(d); if (d !~ /^[0-9.]+$/ && d != "") print $2 "|" (s[id] ? s[id] : "router") "|" d "|" d; next; }
        if ($0 ~ /tunneling request to tcp:/) { d=$0; sub(/^.*tunneling request to tcp:/,"",d); sub(/ via .*$/,"",d); d=clean(d); if (d !~ /^[0-9.]+$/ && d != "") print $2 "|" (s[id] ? s[id] : "router") "|" d "|" d; next; }
      }' >> "$tmp"
  fi
  if [ -f "$ACCESS" ]; then
    $BB tail -250 "$ACCESS" | $BB awk '
      function clean(v){ sub(/^\/\//,"",v); sub(/^tcp:/,"",v); sub(/^udp:/,"",v); sub(/:[0-9]+$/,"",v); return v; }
      / accepted / {
        tm=$2; src=$3; dst=$5; sub(/:[0-9]+$/,"",src); dst=clean(dst);
        if (dst !~ /^[0-9.]+$/ && dst != "") print tm "|" src "|" dst "|" dst;
      }' >> "$tmp"
  fi
}

emit_events(){
  echo -n '['
  $BB tail -140 "$BASE/traffic.events" 2>/dev/null | awk -F'|' '
    BEGIN{first=1}
    NF>=4 && !seen[$2 "|" $3]++ {
      gsub(/"/,"",$1); gsub(/"/,"",$2); gsub(/"/,"",$3); gsub(/"/,"",$4);
      if ($3 !~ /\./ || $3 == "accepted") next;
      if ($2 !~ /^192\.168\.0\./) $2="router";
      if(first==0) printf ",";
      first=0;
      printf "{\"time\":\"%s\",\"src\":\"%s\",\"domain\":\"%s\",\"url\":\"%s\"}",$1,$2,$3,$4;
    }'
  echo -n ']'
}

clear_data(){
  : > "$STATE"
  : > "$BASE/traffic.events"
  : > "$LOG" 2>/dev/null
  : > "$ACCESS" 2>/dev/null
  iptables -Z "$CHAIN" 2>/dev/null
}

printf 'Content-Type: application/json; charset=utf-8\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'

case "$ACTION" in
  clear)
    clear_data
    echo '{"ok":true}'
    ;;
  status|*)
    ensure_chain
    snapshot_counters
    collect_domains
    echo -n '{"now":'
    echo -n "$(uptime_now)"
    echo -n ',"devices":'
    emit_devices
    echo -n ',"events":'
    emit_events
    echo '}'
    ;;
esac
