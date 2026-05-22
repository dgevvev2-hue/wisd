#!/var/tmp/vpnui/bin/busybox-mips ash
# Selective tunnel manager: only selected sites go via VPN, everything
# else goes direct. Stores state in /var/LxC so it survives the /var/tmp
# RAM-wipe on reboot.
#
# Files on the router:
#   /var/LxC/selective.enabled        flag file, presence = selective ON
#   /var/LxC/selective.txt            targets (domain:xxx, ip:1.2.3.4/24)
#                                     with comment markers for presets:
#                                       #preset:youtube ... #endpreset:youtube
#   /var/LxC/selective_scope.txt      LAN device IPs to apply to
#                                     (empty file = apply to whole LAN)
#
# Query string actions:
#   status                            -> current state + targets + scope
#   enable                            -> create flag, restart xray/iptables
#   disable                           -> remove flag, restart xray/iptables
#   preset_on     preset=youtube|telegram|roblox
#   preset_off    preset=youtube|telegram|roblox
#   add_target    value=domain.tld  or  value=1.2.3.4/24
#   del_target    value=...
#   scope_set     value=192.168.0.11,192.168.0.50
#   scope_clear                       -> empty scope = all LAN
#
# All writes are followed by a vpn.cgi restart so iptables/xray pick up
# the new config. No reboot, no factory reset, no file deletion outside
# of the two state files.

BASE=/var/tmp/vpnui
CGI_DIR=$BASE/www/cgi-bin
STORE=/var/LxC
TGT=$STORE/selective.txt
SCOPE=$STORE/selective_scope.txt
EN=$STORE/selective.enabled

ACTION=status
VALUE=
PRESET=

urldecode(){ v=$(echo "$1" | sed 's/+/ /g;s/%/\\x/g'); printf '%b' "$v"; }
for p in $(echo "$QUERY_STRING" | tr '&' ' '); do
  k=${p%%=*}; v=${p#*=}; v=$(urldecode "$v")
  [ "$k" = "action" ] && ACTION=$v
  [ "$k" = "value" ] && VALUE=$v
  [ "$k" = "preset" ] && PRESET=$v
done

safe_target(){ echo "$1" | tr -cd 'A-Za-z0-9*._:/-' ; }
safe_preset(){ echo "$1" | tr -cd 'a-z0-9_'; }
safe_scope(){ echo "$1" | tr -cd '0-9.,'; }

mkdir -p "$STORE"
touch "$TGT" "$SCOPE"

dedupe_targets(){
  [ -f "$TGT" ] || return 0
  awk '
    /^#/ { print; next }
    NF && !seen[$0]++ { print }
  ' "$TGT" > "$TGT.tmp" 2>/dev/null && mv "$TGT.tmp" "$TGT"
}

preset_youtube='domain:youtube.com
domain:youtu.be
domain:ytimg.com
domain:ggpht.com
domain:googlevideo.com
domain:youtube-nocookie.com
domain:yt.be
ip:142.250.0.0/15
ip:172.217.0.0/16
ip:173.194.0.0/16
ip:216.58.192.0/19
ip:64.233.160.0/19'

preset_telegram='domain:telegram.org
domain:t.me
domain:telegram.me
domain:telesco.pe
domain:tdesktop.com
domain:web.telegram.org
domain:cdn-telegram.org
ip:149.154.160.0/20
ip:91.108.4.0/22
ip:91.108.8.0/22
ip:91.108.12.0/22
ip:91.108.16.0/22
ip:91.108.56.0/22'

# Roblox uses AWS/Cloudflare heavily; IP lists are too broad and would
# catch unrelated services, so we rely on SNI sniffing for the domains
# below. If a client ignores SNI we will miss it - acceptable tradeoff.
preset_roblox='domain:roblox.com
domain:rbxcdn.com
domain:rbxstatic.com
domain:robloxlabs.com
domain:rbxsignals.com
domain:roblox.gg'

get_preset(){
  case "$1" in
    youtube)  echo "$preset_youtube"  ;;
    telegram) echo "$preset_telegram" ;;
    roblox)   echo "$preset_roblox"   ;;
  esac
}

preset_is_on(){
  awk -v p="#preset:$1" '$0 == p { found=1 } END { exit found ? 0 : 1 }' "$TGT" 2>/dev/null
}

preset_add(){
  name="$1"
  preset_is_on "$name" && return 0
  body=$(get_preset "$name")
  [ -z "$body" ] && return 1
  {
    echo "#preset:$name"
    echo "$body"
    echo "#endpreset:$name"
  } >> "$TGT"
}

preset_del(){
  name="$1"
  preset_is_on "$name" || return 0
  awk -v n="$name" '
    BEGIN{skip=0}
    $0 == "#preset:" n      {skip=1; next}
    $0 == "#endpreset:" n   {skip=0; next}
    skip==0 {print}
  ' "$TGT" > "$TGT.tmp" && mv "$TGT.tmp" "$TGT"
}

target_add(){
  v=$(safe_target "$1")
  [ -z "$v" ] && return 1
  case "$v" in
    domain:*|ip:*) : ;;
    *)
      # heuristic: contains slash or only digits/dots -> ip, else domain
      case "$v" in
        */*|*[!A-Za-z_-]*) :;;
      esac
      if echo "$v" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?$'; then
        v="ip:$v"
      else
        v="domain:$v"
      fi
      ;;
  esac
  awk -v v="$v" '$0 == v { found=1 } END { exit found ? 0 : 1 }' "$TGT" 2>/dev/null && return 0
  echo "$v" >> "$TGT"
}

target_del(){
  v=$(safe_target "$1")
  [ -z "$v" ] && return 1
  awk -v v="$v" '$0 != v { print }' "$TGT" > "$TGT.tmp" 2>/dev/null
  mv "$TGT.tmp" "$TGT"
}

scope_set(){
  v=$(safe_scope "$1")
  : > "$SCOPE"
  for ip in $(echo "$v" | tr ',' ' '); do
    [ -z "$ip" ] && continue
    echo "$ip" >> "$SCOPE"
  done
}

scope_clear(){
  : > "$SCOPE"
}

restart_vpn(){
  # Only rebuild active xray/iptables when VPN is already running.
  # Settings must never start the tunnel by themselves.
  ps | grep '[x]ray run' >/dev/null 2>&1 || return 0
  [ -x "$CGI_DIR/vpn.cgi" ] || return 0
  QUERY_STRING="action=restart" "$CGI_DIR/vpn.cgi" >/dev/null 2>&1
}

emit_list(){
  file="$1"
  first=1
  echo -n '['
  if [ -s "$file" ]; then
    while read line; do
      [ -z "$line" ] && continue
      case "$line" in '#'*) continue ;; esac
      e=$(echo "$line" | sed 's/\\/\\\\/g;s/"/\\"/g')
      [ "$first" = 0 ] && echo -n ','
      first=0
      echo -n "\"$e\""
    done < "$file"
  fi
  echo -n ']'
}

emit_presets(){
  first=1
  echo -n '{'
  for n in youtube telegram roblox; do
    [ "$first" = 0 ] && echo -n ','
    first=0
    if preset_is_on "$n"; then
      echo -n "\"$n\":true"
    else
      echo -n "\"$n\":false"
    fi
  done
  echo -n '}'
}

status_json(){
  dedupe_targets
  en=false; [ -f "$EN" ] && en=true
  echo -n '{"enabled":'"$en"
  echo -n ',"targets":'; emit_list "$TGT"
  echo -n ',"scope":'; emit_list "$SCOPE"
  echo -n ',"presets":'; emit_presets
  echo '}'
}

printf 'Content-Type: application/json; charset=utf-8\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'

case "$ACTION" in
  enable)
    : > "$EN"
    restart_vpn
    status_json
    ;;
  disable)
    rm -f "$EN"
    restart_vpn
    status_json
    ;;
  preset_on)
    name=$(safe_preset "$PRESET")
    preset_add "$name"
    restart_vpn
    status_json
    ;;
  preset_off)
    name=$(safe_preset "$PRESET")
    preset_del "$name"
    restart_vpn
    status_json
    ;;
  add_target)
    target_add "$VALUE"
    restart_vpn
    status_json
    ;;
  del_target)
    target_del "$VALUE"
    restart_vpn
    status_json
    ;;
  scope_set)
    scope_set "$VALUE"
    restart_vpn
    status_json
    ;;
  scope_clear)
    scope_clear
    restart_vpn
    status_json
    ;;
  status|*)
    status_json
    ;;
esac
