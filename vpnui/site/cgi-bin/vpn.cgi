#!/var/tmp/vpnui/bin/busybox-mips ash
BB=/var/tmp/vpnui/bin/busybox-mips
ROOT=/var/tmp/vpnui/www
XRAY=/var/tmp/xray
BASE=/var/tmp/vpnui
STATE=$BASE/state
MODEFILE=$BASE/mode
START=$BASE/started_at
PID=$BASE/xray.pid
LOG=$BASE/xray.log
STORE=/var/LxC
PSTATE=$STORE/vpnui.state
PMODE=$STORE/vpnui.mode
AUTOSTART=$STORE/vpnui.autostart
SEL_EN=$STORE/selective.enabled
SEL_TGT=$STORE/selective.txt
SEL_SCOPE=$STORE/selective_scope.txt
VPN_ALLOW=$STORE/vpn_clients.allow
VPN_ALLOW_MAC=$STORE/vpn_clients.allowmac
ACTION=status
ID=
MODE=tunnel

urldecode(){ v=$(echo "$1" | sed 's/+/ /g;s/%/\\x/g'); printf '%b' "$v"; }
for p in $(echo "$QUERY_STRING" | tr '&' ' '); do
  k=${p%%=*}; v=${p#*=}; v=$(urldecode "$v")
  [ "$k" = "action" ] && ACTION=$v
  [ "$k" = "id" ] && ID=$v
  [ "$k" = "mode" ] && MODE=$v
done
[ "$MODE" = "proxy" ] || MODE=tunnel

node_line(){ grep "^$1|" "$ROOT/nodes.txt" | head -1; }
node_host(){ node_line "$1" | cut -d '|' -f 3; }
node_ping(){ node_line "$1" | cut -d '|' -f 4; }
node_ips(){ node_line "$1" | cut -d '|' -f 5 | tr ',' ' '; }
json_escape(){ echo "$1" | sed 's/\\/\\\\/g;s/"/\\"/g;s/	/ /g'; }
uptime_now(){ cut -d ' ' -f 1 /proc/uptime | cut -d '.' -f 1; }
is_running(){ ps | grep '[x]ray run' >/dev/null 2>&1; }
nat_enabled(){ iptables -t nat -S PREROUTING 2>/dev/null | grep -qE 'XRAY(_SEL)?'; }
selective_active(){ [ -f "$SEL_EN" ]; }
scope_ips(){
  if [ -s "$SEL_SCOPE" ]; then
    awk 'NF && $0 !~ /^#/' "$SEL_SCOPE"
  else
    echo 192.168.0.0/24
  fi
}
allow_ips(){
  {
    [ -s "$VPN_ALLOW" ] && awk 'NF && $0 !~ /^#/ && $0 ~ /^192\.168\.0\.[0-9]{1,3}$/ {print}' "$VPN_ALLOW"
    if [ -s "$VPN_ALLOW_MAC" ]; then
      awk 'NR>1 && $4!="00:00:00:00:00:00" {print $1 "|" tolower($4)}' /proc/net/arp 2>/dev/null | while IFS='|' read ip mac; do
        echo "$ip" | grep -Eq '^192\.168\.0\.[0-9]{1,3}$' || continue
        awk -v mac="$mac" '$0 == mac { found=1 } END { exit found ? 0 : 1 }' "$VPN_ALLOW_MAC" 2>/dev/null && echo "$ip"
      done
    fi
  } | awk 'NF && !seen[$0]++ { print }'
}
nat_scope_ips(){
  [ -s "$VPN_ALLOW" ] || [ -s "$VPN_ALLOW_MAC" ] || return 0
  if [ ! -s "$SEL_SCOPE" ]; then
    allow_ips
    return 0
  fi
  for aip in $(allow_ips); do
    for sip in $(scope_ips); do
      if [ "$sip" = "192.168.0.0/24" ] || [ "$sip" = "$aip" ]; then
        echo "$aip"
      fi
    done
  done | awk 'NF && !seen[$0]++ { print }'
}
ensure_xray(){
  [ -x "$XRAY" ] && return 0
  if [ -x /var/usbmnt/sda1/vpnui/xray ]; then
    cp /var/usbmnt/sda1/vpnui/xray "$XRAY" 2>/dev/null
    chmod +x "$XRAY" 2>/dev/null
  fi
  [ -x "$XRAY" ]
}
cleanup_nat(){
  while iptables -t nat -S PREROUTING 2>/dev/null | grep -q 'XRAY'; do
    ln=$(iptables -t nat -L PREROUTING --line-numbers -n 2>/dev/null | grep 'XRAY' | awk 'NR==1{print $1}')
    [ -z "$ln" ] && break
    iptables -t nat -D PREROUTING "$ln" 2>/dev/null || break
  done
  # Full tunnel chain (old behavior)
  while iptables -t nat -D PREROUTING -i br2 -s 192.168.0.0/24 -p tcp -j XRAY 2>/dev/null; do :; done
  for ip in $(allow_ips); do
    while iptables -t nat -D PREROUTING -i br2 -s "$ip" -p tcp -j XRAY 2>/dev/null; do :; done
  done
  # Selective chain (selective mode)
  for ip in 192.168.0.0/24 $(scope_ips); do
    while iptables -t nat -D PREROUTING -i br2 -s "$ip" -p tcp --dport 443 -j XRAY_SEL 2>/dev/null; do :; done
  done
  iptables -t nat -F XRAY_SEL 2>/dev/null
  iptables -t nat -X XRAY_SEL 2>/dev/null
  # Selective UDP/443 REJECT (forces QUIC fallback to TCP)
  while iptables -D FORWARD -m comment --comment XRAY_SEL_UDP -j REJECT --reject-with icmp-port-unreachable 2>/dev/null; do :; done
  for ip in 192.168.0.0/24 $(allow_ips) $(scope_ips); do
    while iptables -D FORWARD -i br2 -s "$ip" -p udp --dport 443 -j REJECT --reject-with icmp-port-unreachable 2>/dev/null; do :; done
  done
  # old mark-style leftover rules (if any)
  while iptables -S FORWARD 2>/dev/null | grep -q XRAY_SEL_UDP; do
    ln=$(iptables -L FORWARD --line-numbers -n 2>/dev/null | grep XRAY_SEL_UDP | awk 'NR==1{print $1}')
    [ -z "$ln" ] && break
    iptables -D FORWARD "$ln" 2>/dev/null || break
  done
}
add_udp_reject(){
  sip="$1"
  [ -z "$sip" ] && return 0
  iptables -I FORWARD 1 -i br2 -s "$sip" -p udp --dport 443 -m comment --comment XRAY_SEL_UDP -j REJECT --reject-with icmp-port-unreachable 2>/dev/null && return 0
  iptables -I FORWARD 1 -i br2 -s "$sip" -p udp --dport 443 -j REJECT --reject-with icmp-port-unreachable 2>/dev/null
}
stop_vpn(){
  cleanup_nat
  killall xray 2>/dev/null
  rm -f "$PID" "$START"
}
clear_logs(){
  : > "$LOG"
  : > "$BASE/xray.access.log"
  : > "$BASE/traffic.tmp"
}
build_selective_rules(){
  tmp="$BASE/sel_rules.json"
  : > "$tmp"
  list="$BASE/sel_domain.list"
  iplist="$BASE/sel_ip.list"
  : > "$list"
  : > "$iplist"
  while read r; do
    [ -z "$r" ] && continue
    case "$r" in
      '#'*) continue ;;
      domain:*) echo "$r" >> "$list" ;;
      ip:*) echo "${r#ip:}" >> "$iplist" ;;
    esac
  done < "$SEL_TGT"
  awk 'NF && !seen[$0]++ { print }' "$list" > "$list.tmp" 2>/dev/null
  mv "$list.tmp" "$list"
  awk 'NF && !seen[$0]++ { print }' "$iplist" > "$iplist.tmp" 2>/dev/null
  mv "$iplist.tmp" "$iplist"
  first_rule=1
  if [ -s "$list" ]; then
    [ "$first_rule" = 0 ] && echo ',' >> "$tmp"
    first_rule=0
    echo '      {' >> "$tmp"
    echo '        "type": "field",' >> "$tmp"
    echo '        "outboundTag": "vpn-out",' >> "$tmp"
    echo '        "domain": [' >> "$tmp"
    first=1
    while read d; do
      [ -z "$d" ] && continue
      [ "$first" = 0 ] && echo ',' >> "$tmp"
      first=0
      printf '          "%s"' "$d" >> "$tmp"
    done < "$list"
    echo '' >> "$tmp"
    echo '        ],' >> "$tmp"
    echo '        "tag": "sel-domains"' >> "$tmp"
    echo '      }' >> "$tmp"
  fi
  if [ -s "$iplist" ]; then
    [ "$first_rule" = 0 ] && echo ',' >> "$tmp"
    first_rule=0
    echo '      {' >> "$tmp"
    echo '        "type": "field",' >> "$tmp"
    echo '        "outboundTag": "vpn-out",' >> "$tmp"
    echo '        "ip": [' >> "$tmp"
    first=1
    while read ip; do
      [ -z "$ip" ] && continue
      [ "$first" = 0 ] && echo ',' >> "$tmp"
      first=0
      printf '          "%s"' "$ip" >> "$tmp"
    done < "$iplist"
    echo '' >> "$tmp"
    echo '        ],' >> "$tmp"
    echo '        "tag": "sel-ips"' >> "$tmp"
    echo '      }' >> "$tmp"
  fi
  [ "$first_rule" = 0 ] && echo ',' >> "$tmp"
  echo '      {' >> "$tmp"
  echo '        "type": "field",' >> "$tmp"
  echo '        "outboundTag": "direct",' >> "$tmp"
  echo '        "inboundTag": ["redir-in", "socks-in", "http-in"],' >> "$tmp"
  echo '        "network": "tcp,udp",' >> "$tmp"
  echo '        "port": "0-65535",' >> "$tmp"
  echo '        "tag": "sel-default"' >> "$tmp"
  echo '      }' >> "$tmp"
  awk -v ins="$tmp" '
    BEGIN {
      while ((getline line < ins) > 0) body = body line "\n"
      close(ins)
    }
    !done && /"rules"[ \t]*:[ \t]*\[/ {
      sub(/"rules"[ \t]*:[ \t]*\[/, "\"rules\":[\n" body)
      done=1
    }
    { print }
  ' "$BASE/active.json" > "$BASE/active.new" && mv "$BASE/active.new" "$BASE/active.json"
}
build_active(){
  src="$1"
  cp "$src" "$BASE/active.json"
  if selective_active; then
    build_selective_rules
    return 0
  fi
  tmp="$BASE/direct_domains.json"
  iptmp="$BASE/direct_ips.json"
  list="$BASE/direct_domains.list"
  iplist="$BASE/direct_ips.list"
  : > "$list"
  : > "$iplist"
  if [ -f "$STORE/rules.txt" ]; then
    while read r; do
      [ -z "$r" ] && continue
      echo "$r" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?$' && { echo "$r" >> "$iplist"; continue; }
      d=$(echo "$r" | sed 's/^\*\.//')
      case "$d" in
        geoip:*) echo "$d" >> "$iplist" ;;
        domain:*|regexp:*|geosite:*|full:*) echo "$d" >> "$list" ;;
        *) [ -n "$d" ] && echo "domain:$d" >> "$list" ;;
      esac
    done < "$STORE/rules.txt"
  fi
  awk 'NF && !seen[$0]++ { print }' "$list" > "$list.tmp" 2>/dev/null
  mv "$list.tmp" "$list"
  awk 'NF && !seen[$0]++ { print }' "$iplist" > "$iplist.tmp" 2>/dev/null
  mv "$iplist.tmp" "$iplist"
  if [ ! -s "$list" ] && [ ! -s "$iplist" ]; then
    return 0
  fi
  : > "$tmp"
  first_rule=1
  if [ -s "$list" ]; then
    [ "$first_rule" = 0 ] && echo ',' >> "$tmp"
    first_rule=0
    echo '      {' >> "$tmp"
    echo '        "type": "field",' >> "$tmp"
    echo '        "outboundTag": "direct",' >> "$tmp"
    echo '        "domain": [' >> "$tmp"
    first=1
    while read d; do
      [ -z "$d" ] && continue
      [ "$first" = 0 ] && echo ',' >> "$tmp"
      first=0
      printf '          "%s"' "$d" >> "$tmp"
    done < "$list"
    echo '' >> "$tmp"
    echo '        ],' >> "$tmp"
    echo '        "tag": "direct-user"' >> "$tmp"
    echo '      }' >> "$tmp"
  fi
  if [ -s "$iplist" ]; then
    [ "$first_rule" = 0 ] && echo ',' >> "$tmp"
    first_rule=0
    echo '      {' >> "$tmp"
    echo '        "type": "field",' >> "$tmp"
    echo '        "outboundTag": "direct",' >> "$tmp"
    echo '        "ip": [' >> "$tmp"
    first=1
    while read ip; do
      [ -z "$ip" ] && continue
      [ "$first" = 0 ] && echo ',' >> "$tmp"
      first=0
      printf '          "%s"' "$ip" >> "$tmp"
    done < "$iplist"
    echo '' >> "$tmp"
    echo '        ],' >> "$tmp"
    echo '        "tag": "direct-user-ip"' >> "$tmp"
    echo '      }' >> "$tmp"
  fi
  awk -v ins="$tmp" '
    BEGIN {
      while ((getline line < ins) > 0) body = body line "\n"
      close(ins)
    }
    !done && /"rules"[ \t]*:[ \t]*\[/ {
      sub(/"rules"[ \t]*:[ \t]*\[/, "\"rules\":[\n" body)
      done=1
    }
    { print }
  ' "$BASE/active.json" > "$BASE/active.new" && mv "$BASE/active.new" "$BASE/active.json"
}
apply_nat_sel(){
  id="$1"
  [ -s "$VPN_ALLOW" ] || [ -s "$VPN_ALLOW_MAC" ] || return 0
  iptables -t nat -N XRAY_SEL 2>/dev/null
  iptables -t nat -F XRAY_SEL
  for cidr in 10.0.0.0/8 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4; do
    iptables -t nat -A XRAY_SEL -d $cidr -j RETURN
  done
  for ip in $(node_ips "$id"); do [ -n "$ip" ] && iptables -t nat -A XRAY_SEL -d "$ip/32" -j RETURN; done
  iptables -t nat -A XRAY_SEL -p tcp -j REDIRECT --to-ports 12345
  for sip in $(nat_scope_ips); do
    iptables -t nat -I PREROUTING 1 -i br2 -s "$sip" -p tcp --dport 443 -j XRAY_SEL
    add_udp_reject "$sip"
  done
}
apply_nat(){
  id="$1"; mode="$2"
  [ "$mode" = "tunnel" ] || return 0
  if selective_active; then
    apply_nat_sel "$id"
    return 0
  fi
  [ -s "$VPN_ALLOW" ] || [ -s "$VPN_ALLOW_MAC" ] || return 0
  iptables -t nat -N XRAY 2>/dev/null
  iptables -t nat -F XRAY
  for src in $(grep -E '^([0-9]{1,3}\.){3}[0-9]{1,3}$' "$STORE/rules.txt" 2>/dev/null); do
    iptables -t nat -A XRAY -s "$src" -j RETURN
  done
  for cidr in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4; do
    iptables -t nat -A XRAY -d $cidr -j RETURN
  done
  for ip in $(node_ips "$id"); do [ -n "$ip" ] && iptables -t nat -A XRAY -d "$ip/32" -j RETURN; done
  iptables -t nat -A XRAY -p tcp -j REDIRECT --to-ports 12345
  for src in $(allow_ips); do
    iptables -t nat -I PREROUTING 1 -i br2 -s "$src" -p tcp -j XRAY
  done
}
open_ports(){
  for port in 1080 1081 12345; do
    iptables -C INPUT -i br2 -p tcp --dport "$port" -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -i br2 -p tcp --dport "$port" -j ACCEPT
  done
}
start_vpn(){
  id="$1"; mode="$2"
  [ -f "$ROOT/configs/$id.json" ] || return 2
  ensure_xray || return 3
  stop_vpn
  build_active "$ROOT/configs/$id.json"
  : > "$LOG"; : > "$BASE/xray.access.log"
  (XRAY_LOCATION_ASSET="$BASE" "$XRAY" run -config "$BASE/active.json" >> "$LOG" 2>&1 & echo $! > "$PID")
  sleep 1
  is_running || return 4
  cleanup_nat
  apply_nat "$id" "$mode"
  open_ports
  echo "$id" > "$STATE"; echo "$mode" > "$MODEFILE"; uptime_now > "$START"
  echo "$id" > "$PSTATE"; echo "$mode" > "$PMODE"; echo 1 > "$AUTOSTART"
  return 0
}
status_json(){
  id=""; [ -f "$STATE" ] && id=$(cat "$STATE")
  [ -z "$id" ] && [ -f "$PSTATE" ] && id=$(cat "$PSTATE")
  mode="tunnel"; [ -f "$MODEFILE" ] && mode=$(cat "$MODEFILE")
  [ ! -f "$MODEFILE" ] && [ -f "$PMODE" ] && mode=$(cat "$PMODE")
  started=""; elapsed=0
  if [ -f "$START" ]; then
    started=$(cat "$START")
    now=$(uptime_now)
    elapsed=$((now-started))
    [ "$elapsed" -lt 0 ] && elapsed=0
  fi
  host=$(json_escape "$(node_host "$id")")
  ping=$(node_ping "$id")
  running=false; is_running && running=true
  nat=false; nat_enabled && nat=true
  enabled=false; [ "$running" = true ] && enabled=true
  selective=false; selective_active && selective=true
  sel_count=0
  [ -s "$SEL_TGT" ] && sel_count=$(grep -cE '^(domain|ip):' "$SEL_TGT" 2>/dev/null)
  echo "{\"enabled\":$enabled,\"running\":$running,\"nat\":$nat,\"selective\":$selective,\"selectiveCount\":$sel_count,\"id\":\"$id\",\"mode\":\"$mode\",\"host\":\"$host\",\"ping\":\"$ping\",\"started\":\"$started\",\"elapsed\":$elapsed,\"message\":\"ok\"}"
}

printf 'Content-Type: application/json; charset=utf-8\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'
case "$ACTION" in
  connect)
    start_vpn "$ID" "$MODE"; rc=$?
    if [ "$rc" = 0 ]; then status_json; else echo "{\"enabled\":false,\"id\":\"$ID\",\"mode\":\"$MODE\",\"message\":\"connect failed rc=$rc\"}"; fi
    ;;
  disconnect)
    stop_vpn
    rm -f "$AUTOSTART"
    echo '{"enabled":false,"running":false,"nat":false,"id":"","mode":"tunnel","host":"","ping":"","started":"","elapsed":0,"message":"disabled"}'
    ;;
  restart)
    id=""; [ -f "$STATE" ] && id=$(cat "$STATE")
    mode="tunnel"; [ -f "$MODEFILE" ] && mode=$(cat "$MODEFILE")
    [ -n "$ID" ] && id="$ID"
    start_vpn "$id" "$mode"; rc=$?
    if [ "$rc" = 0 ]; then status_json; else echo "{\"enabled\":false,\"id\":\"$id\",\"mode\":\"$mode\",\"message\":\"restart failed rc=$rc\"}"; fi
    ;;
  clearlogs)
    clear_logs
    echo '{"ok":true,"message":"logs cleared"}'
    ;;
  status|*)
    status_json
    ;;
esac
