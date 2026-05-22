#!/var/tmp/vpnui/bin/busybox-mips ash
BASE=/var/LxC/tgbot
TOKEN_FILE=$BASE/token
ALLOWED_FILE=$BASE/allowed_chat
OFFSET_FILE=$BASE/offset
PID_FILE=$BASE/pid
LOG_FILE=$BASE/bot.log
XRAY=/var/tmp/xray
BOT_XRAY_CONFIG=$BASE/bot-xray.json
BOT_XRAY_PID=$BASE/bot-xray.pid
BOT_XRAY_LOG=$BASE/bot-xray.log
CURL=/usr/sbin/curl
CURL_PROXY=
VPN_CGI=/var/tmp/vpnui/www/cgi-bin/vpn.cgi
DNS_CGI=/var/tmp/vpnui/www/cgi-bin/dns.cgi
PING_CGI=/var/tmp/vpnui/www/cgi-bin/ping.cgi
INFO_CGI=/var/tmp/vpnui/www/cgi-bin/info.cgi
AUTO_CGI=/var/tmp/vpnui/www/cgi-bin/auto.cgi
NODES=/var/tmp/vpnui/www/nodes.txt

mkdir -p "$BASE"

ensure_tg_route() {
  ensure_bot_xray
  for net in 149.154.160.0/20 91.108.4.0/22 91.108.8.0/22 91.108.12.0/22 91.108.16.0/22 91.108.56.0/22; do
    iptables -t nat -C OUTPUT -p tcp -d "$net" --dport 443 -j REDIRECT --to-ports 12346 2>/dev/null || iptables -t nat -I OUTPUT 1 -p tcp -d "$net" --dport 443 -j REDIRECT --to-ports 12346 2>/dev/null
  done
}
bot_xray_running() {
  [ -f "$BOT_XRAY_PID" ] || return 1
  pid=`cat "$BOT_XRAY_PID" 2>/dev/null`
  [ -n "$pid" ] || return 1
  ps | grep "^[ ]*$pid " | grep -v grep >/dev/null 2>&1
}
ensure_xray_bin() {
  [ -x "$XRAY" ] && return 0
  if [ -x /var/usbmnt/sda1/vpnui/xray ]; then
    cp /var/usbmnt/sda1/vpnui/xray "$XRAY" 2>/dev/null
    chmod +x "$XRAY" 2>/dev/null
  fi
  [ -x "$XRAY" ]
}
write_bot_xray_config() {
  [ -s "$BOT_XRAY_CONFIG" ] && return 0
  src=/var/tmp/vpnui/www/configs/0.json
  [ -f /var/LxC/vpnui.state ] && id=`cat /var/LxC/vpnui.state 2>/dev/null` || id=0
  [ -f "/var/tmp/vpnui/www/configs/$id.json" ] && src="/var/tmp/vpnui/www/configs/$id.json"
  awk '
    BEGIN{skip=0; first=1}
    /"outbounds"[ \t]*:[ \t]*\[/ {out=1}
    out {
      if ($0 ~ /"tag"[ \t]*:[ \t]*"direct"/) skip=1
      if (!skip) {
        if (first) { print "{"; print "  \"log\": {\"loglevel\": \"warning\"},"; print "  \"inbounds\": ["; print "    {\"tag\":\"bot-socks\",\"listen\":\"127.0.0.1\",\"port\":1090,\"protocol\":\"socks\",\"settings\":{\"auth\":\"noauth\",\"udp\":false}},"; print "    {\"tag\":\"bot-http\",\"listen\":\"127.0.0.1\",\"port\":1091,\"protocol\":\"http\",\"settings\":{}}"; print "  ],"; print "  \"outbounds\": ["; first=0 }
        print
      }
      if (skip && $0 ~ /^[ \t]*}[,]?[ \t]*$/) skip=0
    }
  ' "$src" | sed 's/"outbounds"[ \t]*:[ \t]*\[//' | sed 's/^[ \t]*//' > "$BOT_XRAY_CONFIG.tmp"
  echo '  ], "routing": {"rules": []}}' >> "$BOT_XRAY_CONFIG.tmp"
  mv "$BOT_XRAY_CONFIG.tmp" "$BOT_XRAY_CONFIG"
}
ensure_bot_xray() {
  bot_xray_running && return 0
  ensure_xray_bin || return 1
  write_bot_xray_config
  "$XRAY" run -config "$BOT_XRAY_CONFIG" >> "$BOT_XRAY_LOG" 2>&1 &
  echo $! > "$BOT_XRAY_PID"
  sleep 2
  bot_xray_running
}
body_only() { tr -d '\r' | sed '1,/^$/d'; }
esc_html() { sed 's/&/\&amp;/g;s/</\&lt;/g;s/>/\&gt;/g'; }
json_get() {
  key="$1"
  sed -n "s/.*\"$key\":\"\\([^\"]*\\)\".*/\\1/p" | head -1
}
json_bool() {
  key="$1"
  sed -n "s/.*\"$key\":\\(true\\|false\\).*/\\1/p" | head -1
}
json_num() {
  key="$1"
  sed -n "s/.*\"$key\":\\([0-9]*\\).*/\\1/p" | head -1
}
token() {
  [ -s "$TOKEN_FILE" ] || return 1
  cat "$TOKEN_FILE"
}
api() {
  t=`token` || return 1
  echo "https://api.telegram.org/bot$t/$1"
}
curl_cmd() {
  ensure_tg_route
  if [ -n "$CURL_PROXY" ]; then
    "$CURL" -k -s --connect-timeout 12 --socks5-hostname "$CURL_PROXY" "$@"
  else
    "$CURL" -k -s --connect-timeout 12 "$@"
  fi
}
send_msg() {
  chat="$1"; text="$2"
  url=`api sendMessage` || return 1
  kb='{"keyboard":[[{"text":"/status"},{"text":"/tunnel 0"},{"text":"/off"}],[{"text":"/servers"},{"text":"/ping ya.ru"},{"text":"/dns full"}],[{"text":"/info"},{"text":"/auto_on"},{"text":"/auto_off"}]],"resize_keyboard":true}'
  curl_cmd \
    --data-urlencode "chat_id=$chat" \
    --data-urlencode "text=$text" \
    --data-urlencode "parse_mode=HTML" \
    --data-urlencode "reply_markup=$kb" \
    "$url" >/dev/null 2>&1
}
allowed() {
  chat="$1"
  if [ ! -s "$ALLOWED_FILE" ]; then
    echo "$chat" > "$ALLOWED_FILE"
    return 0
  fi
  grep -qx "$chat" "$ALLOWED_FILE" 2>/dev/null
}
vpn_json() {
  QUERY_STRING="$1" "$VPN_CGI" 2>/dev/null | body_only
}
dns_json() {
  QUERY_STRING="$1" "$DNS_CGI" 2>/dev/null | body_only
}
ping_json() {
  QUERY_STRING="$1" "$PING_CGI" 2>/dev/null | body_only
}
info_json() {
  QUERY_STRING="$1" "$INFO_CGI" 2>/dev/null | body_only
}
auto_json() {
  QUERY_STRING="$1" "$AUTO_CGI" 2>/dev/null | body_only
}
status_text() {
  j=`vpn_json action=status`
  en=`echo "$j" | json_bool enabled`
  nat=`echo "$j" | json_bool nat`
  id=`echo "$j" | json_get id`
  mode=`echo "$j" | json_get mode`
  host=`echo "$j" | json_get host`
  ping=`echo "$j" | json_get ping`
  elapsed=`echo "$j" | json_num elapsed`
  [ -z "$elapsed" ] && elapsed=0
  h=$((elapsed/3600)); m=$(((elapsed%3600)/60)); s=$((elapsed%60))
  [ "$en" = true ] && state=ON || state=OFF
  [ "$nat" = true ] && natstate=ON || natstate=OFF
  printf '<b>Router VPN</b>\nVPN: <b>%s</b>\nMode: <b>%s</b>\nTunnel NAT: <b>%s</b>\nServer: <b>%s</b>\nHost: <code>%s</code>\nPing: <b>%s ms</b>\nUptime: <b>%02d:%02d:%02d</b>' "$state" "$mode" "$natstate" "$id" "$host" "$ping" "$h" "$m" "$s"
}
dns_text() {
  j=`dns_json action=status`
  mode=`echo "$j" | json_get mode`
  resolvers=`echo "$j" | json_get resolvers`
  red=`echo "$j" | json_bool dnsRedirect`
  dot=`echo "$j" | json_bool dotBlock`
  ad=`echo "$j" | json_bool adBlock`
  printf '<b>DNS protection</b>\nMode: <b>%s</b>\nResolvers: <code>%s</code>\nDNS redirect: <b>%s</b>\nDoT block: <b>%s</b>\nAd block: <b>%s</b>' "$mode" "$resolvers" "$red" "$dot" "$ad"
}
info_text() {
  j=`info_json ''`
  load=`echo "$j" | json_get load`
  up=`echo "$j" | json_num uptime`
  vpn=`echo "$j" | sed -n 's/.*"vpn":\(true\|false\).*/\1/p' | head -1`
  http=`echo "$j" | sed -n 's/.*"http":\(true\|false\).*/\1/p' | head -1`
  printf '<b>Router info</b>\nUptime: <b>%s sec</b>\nLoad: <b>%s</b>\nVPN process: <b>%s</b>\nPanel: <b>%s</b>' "$up" "$load" "$vpn" "$http"
}
servers_text() {
  out='<b>Servers</b>'
  n=0
  while IFS='|' read id name host ping ips; do
    [ -z "$id" ] && continue
    safe=`echo "$name" | esc_html`
    out="$out
$id: $safe | ${ping} ms | <code>$host</code>"
    n=$((n+1))
    [ "$n" -ge 20 ] && break
  done < "$NODES"
  echo "$out"
}
help_text() {
  cat <<'EOF'
<b>Router VPN bot</b>
/status - VPN status
/tunnel 0 - tunnel mode, server 0
/proxy 0 - proxy mode, server 0
/off - disable VPN
/restart - restart VPN
/servers - server list
/ping ya.ru - ping host
/dns full - DNS full
/dns adguard - DNS AdGuard
/dns quad9 - DNS Quad9
/dns provider - provider DNS
/auto_on - auto switch ON
/auto_off - auto switch OFF
/info - router info
/panel - panel link
EOF
}
run_command() {
  chat="$1"; text="$2"
  allowed "$chat" || { send_msg "$chat" "Access denied. chat_id: <code>$chat</code>"; return; }
  set -- $text
  cmd="$1"; a="$2"; b="$3"
  echo "cmd chat=$chat text=$text" >> "$LOG_FILE"
  case "$cmd" in
    /start|/help|help) send_msg "$chat" "`help_text`" ;;
    /status|status) send_msg "$chat" "`status_text`" ;;
    /panel) send_msg "$chat" "Panel: http://192.168.0.1:8083/" ;;
    /servers|servers) send_msg "$chat" "`servers_text`" ;;
    /tunnel|tunnel)
      [ -z "$a" ] && a=0
      vpn_json "action=connect&id=$a&mode=tunnel" >/dev/null
      send_msg "$chat" "Tunnel ON\n\n`status_text`"
      ;;
    /proxy|proxy)
      [ -z "$a" ] && a=0
      vpn_json "action=connect&id=$a&mode=proxy" >/dev/null
      send_msg "$chat" "Proxy ON\n\n`status_text`"
      ;;
    /off|off)
      vpn_json "action=disconnect" >/dev/null
      send_msg "$chat" "VPN OFF"
      ;;
    /restart|restart)
      vpn_json "action=restart" >/dev/null
      send_msg "$chat" "VPN restarted\n\n`status_text`"
      ;;
    /ping|ping)
      [ -z "$a" ] && a=8.8.8.8
      j=`ping_json "host=$a"`
      p=`echo "$j" | sed -n 's/.*"ping":\([^,}]*\).*/\1/p' | head -1`
      h=`echo "$j" | json_get host`
      send_msg "$chat" "Ping <code>$h</code>: <b>$p ms</b>"
      ;;
    /dns|dns)
      [ -z "$a" ] && { send_msg "$chat" "`dns_text`"; return; }
      case "$a" in full|adguard|quad9|provider) dns_json "action=apply&mode=$a" >/dev/null; send_msg "$chat" "`dns_text`" ;; *) send_msg "$chat" "DNS: full/adguard/quad9/provider" ;; esac
      ;;
    /auto_on|auto_on)
      auto_json "action=start&threshold=100&interval=600" >/dev/null
      send_msg "$chat" "Auto switch ON: 100 ms / 10 min"
      ;;
    /auto_off|auto_off)
      auto_json "action=stop" >/dev/null
      send_msg "$chat" "Auto switch OFF"
      ;;
    /info|info) send_msg "$chat" "`info_text`" ;;
    *) send_msg "$chat" "Unknown command. /help" ;;
  esac
}
poll_once() {
  off=0; [ -f "$OFFSET_FILE" ] && off=`cat "$OFFSET_FILE"`
  next=$((off+1))
  url=`api "getUpdates?timeout=25&offset=$next"` || return 1
  data=`curl_cmd "$url"`
  [ -z "$data" ] && { echo "empty updates response" >> "$LOG_FILE"; return; }
  echo "$data" | sed 's/},{"update_id"/}\n{"update_id"/g' | grep '"update_id"' | while read line; do
    uid=`echo "$line" | sed -n 's/.*"update_id":\([0-9]*\).*/\1/p'`
    chat=`echo "$line" | sed -n 's/.*"chat":{[^}]*"id":\(-*[0-9]*\).*/\1/p'`
    text=`echo "$line" | sed -n 's/.*"text":"\([^"]*\)".*/\1/p' | sed 's#\\/#/#g;s#\\"#"#g'`
    [ -n "$uid" ] && echo "$uid" > "$OFFSET_FILE"
    if [ -n "$chat" ] && [ -n "$text" ]; then
      run_command "$chat" "$text"
    else
      echo "skip update=$uid chat=$chat text=$text" >> "$LOG_FILE"
    fi
  done
}
daemon() {
  ensure_tg_route
  echo "started `date 2>/dev/null`" >> "$LOG_FILE"
  while true; do
    poll_once >> "$LOG_FILE" 2>&1
    sleep 2
  done
}
case "$1" in
  start)
    if [ -f "$PID_FILE" ] && kill -0 `cat "$PID_FILE"` 2>/dev/null; then echo already; exit 0; fi
    trap '' HUP
    daemon >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo started
    ;;
  stop)
    [ -f "$PID_FILE" ] && kill `cat "$PID_FILE"` 2>/dev/null
    rm -f "$PID_FILE"
    echo stopped
    ;;
  restart)
    "$0" stop
    sleep 1
    "$0" start
    ;;
  status)
    if [ -f "$PID_FILE" ] && kill -0 `cat "$PID_FILE"` 2>/dev/null; then echo running; else echo stopped; fi
    ;;
  once) poll_once ;;
  *) echo "usage: $0 start|stop|restart|status|once" ;;
esac
