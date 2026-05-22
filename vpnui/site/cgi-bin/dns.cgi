#!/var/tmp/vpnui/bin/busybox-mips ash
BASE=/var/tmp/vpnui
MODEFILE=$BASE/dns_mode
ACTION=status
MODE=full
urldecode(){ v=$(echo "$1" | sed 's/+/ /g;s/%/\\x/g'); printf '%b' "$v"; }
for p in $(echo "$QUERY_STRING" | tr '&' ' '); do
  k=${p%%=*}; v=${p#*=}; v=$(urldecode "$v")
  [ "$k" = "action" ] && ACTION=$v
  [ "$k" = "mode" ] && MODE=$v
done
safe_mode(){
  case "$1" in
    full|adguard|quad9|provider) echo "$1" ;;
    *) echo full ;;
  esac
}
write_resolv(){
  m=$(safe_mode "$1")
  cp /etc/resolv.conf /etc/resolv.conf.bak.vpnui 2>/dev/null
  case "$m" in
    adguard)
      printf 'nameserver 94.140.14.14\nnameserver 94.140.15.15\n' > /etc/resolv.conf
      ;;
    quad9)
      printf 'nameserver 9.9.9.9\nnameserver 149.112.112.112\n' > /etc/resolv.conf
      ;;
    provider)
      if [ -f /etc/resolv.conf.bak.vpnui ]; then
        cp /etc/resolv.conf.bak.vpnui /etc/resolv.conf
      else
        printf 'nameserver 5.141.95.254\nnameserver 5.141.95.250\n' > /etc/resolv.conf
      fi
      ;;
    full|*)
      printf 'nameserver 94.140.14.14\nnameserver 94.140.15.15\nnameserver 9.9.9.9\nnameserver 149.112.112.112\n' > /etc/resolv.conf
      ;;
  esac
  echo "$m" > "$MODEFILE"
}
enable_rules(){
  iptables -t nat -C PREROUTING -i br2 -p udp --dport 53 -j REDIRECT --to-ports 53 2>/dev/null || iptables -t nat -I PREROUTING 1 -i br2 -p udp --dport 53 -j REDIRECT --to-ports 53
  iptables -t nat -C PREROUTING -i br2 -p tcp --dport 53 -j REDIRECT --to-ports 53 2>/dev/null || iptables -t nat -I PREROUTING 1 -i br2 -p tcp --dport 53 -j REDIRECT --to-ports 53
  iptables -C INPUT -i br2 -p udp --dport 53 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -i br2 -p udp --dport 53 -j ACCEPT
  iptables -C INPUT -i br2 -p tcp --dport 53 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -i br2 -p tcp --dport 53 -j ACCEPT
  iptables -C FORWARD -i br2 -p tcp --dport 853 -j REJECT 2>/dev/null || iptables -I FORWARD 1 -i br2 -p tcp --dport 853 -j REJECT
}
disable_rules(){
  while iptables -t nat -D PREROUTING -i br2 -p udp --dport 53 -j REDIRECT --to-ports 53 2>/dev/null; do :; done
  while iptables -t nat -D PREROUTING -i br2 -p tcp --dport 53 -j REDIRECT --to-ports 53 2>/dev/null; do :; done
  while iptables -D FORWARD -i br2 -p tcp --dport 853 -j REJECT 2>/dev/null; do :; done
}
json_escape(){ echo "$1" | sed 's/\\/\\\\/g;s/"/\\"/g;s/	/ /g'; }
status_json(){
  mode=provider; [ -f "$MODEFILE" ] && mode=$(cat "$MODEFILE")
  resolv=$(cat /etc/resolv.conf 2>/dev/null | awk '/^nameserver/ {print $2}' | tr '\n' ' ')
  dnsRedirect=false
  dotBlock=false
  iptables -t nat -S PREROUTING 2>/dev/null | grep -q -- '--dport 53' && dnsRedirect=true
  iptables -S FORWARD 2>/dev/null | grep -q -- '--dport 853' && dotBlock=true
  adBlock=false
  nslookup doubleclick.net 127.0.0.1 2>/dev/null | grep -Eq '0\.0\.0\.0|::' && adBlock=true
  echo "{\"mode\":\"$(json_escape "$mode")\",\"resolvers\":\"$(json_escape "$resolv")\",\"dnsRedirect\":$dnsRedirect,\"dotBlock\":$dotBlock,\"adBlock\":$adBlock}"
}
mkdir -p "$BASE"
case "$ACTION" in
  apply)
    MODE=$(safe_mode "$MODE")
    write_resolv "$MODE"
    if [ "$MODE" = "provider" ]; then disable_rules; else enable_rules; fi
    killall -HUP dnsmasq 2>/dev/null
    ;;
  status|*) ;;
esac
printf 'Content-Type: application/json; charset=utf-8\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'
status_json
