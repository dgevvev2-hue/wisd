#!/var/tmp/vpnui/bin/busybox-mips ash
BASE=/var/tmp/vpnui
ROOT=/var/tmp/vpnui/www
USBROOT=/var/usbmnt/sda1/vpnui/www
BB=/var/tmp/vpnui/bin/busybox-mips
RWGET=/var/tmp/vpnui/bin/rwget
STORE=/var/LxC
URLFILE=$STORE/subscription.url
SUBS=$STORE/subscriptions.txt
ACTIVE=$STORE/subscription.active
RAW=$BASE/subscription.raw
LINKS=$BASE/subscription.links
ACTION=save
URL=
NAME=
ID=

urldecode(){ v=$(echo "$1" | sed 's/+/ /g;s/%/\\x/g'); printf '%b' "$v"; }
json_escape(){ echo "$1" | sed 's/\\/\\\\/g;s/"/\\"/g;s/	/ /g'; }
is_ip(){
  echo "$1" | awk -F. 'NF==4 {
    for (i=1; i<=4; i++) if ($i !~ /^[0-9]+$/ || $i < 0 || $i > 255) exit 1
    exit 0
  } { exit 1 }'
}
qget(){
  echo "$1" | tr '&' '\n' | while read p; do
    k=${p%%=*}; v=${p#*=}
    [ "$k" = "$2" ] && { urldecode "$v"; break; }
  done
}

for p in $(echo "$QUERY_STRING" | tr '&' ' '); do
  k=${p%%=*}; v=${p#*=}; v=$(urldecode "$v")
  [ "$k" = "action" ] && ACTION=$v
  [ "$k" = "url" ] && URL=$v
  [ "$k" = "name" ] && NAME=$v
  [ "$k" = "id" ] && ID=$v
done

printf 'Content-Type: application/json; charset=utf-8\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'
mkdir -p "$BASE" "$ROOT/configs" "$STORE"
touch "$SUBS"

safe_id(){ echo "$1" | tr -cd 'A-Za-z0-9._-'; }
safe_name(){ echo "$1" | tr -cd 'A-Za-z0-9 ._:-'; }
new_id(){ echo "sub$(date +%s 2>/dev/null)$$"; }
is_direct_vless(){
  case "$1" in
    vless://*) return 0 ;;
  esac
  return 1
}
sub_url_by_id(){ awk -F'|' -v id="$1" '$1==id {print $3; exit}' "$SUBS" 2>/dev/null; }
sub_name_by_id(){ awk -F'|' -v id="$1" '$1==id {print $2; exit}' "$SUBS" 2>/dev/null; }
upsert_sub(){
  id="$1"; name="$2"; url="$3"; count="$4"
  [ -z "$id" ] && id=$(new_id)
  [ -z "$name" ] && name="$url"
  name=$(safe_name "$name")
  tmp="$SUBS.tmp"
  awk -F'|' -v id="$id" '$1!=id {print}' "$SUBS" 2>/dev/null > "$tmp"
  echo "$id|$name|$url|$count|$(date +%s 2>/dev/null)" >> "$tmp"
  mv "$tmp" "$SUBS"
  echo "$id" > "$ACTIVE"
  echo "$url" > "$URLFILE"
}
delete_sub(){
  id=$(safe_id "$1")
  [ -z "$id" ] && return 0
  tmp="$SUBS.tmp"
  awk -F'|' -v id="$id" '$1!=id {print}' "$SUBS" 2>/dev/null > "$tmp"
  mv "$tmp" "$SUBS"
  if [ -f "$ACTIVE" ] && [ "$(cat "$ACTIVE")" = "$id" ]; then
    next=$(awk -F'|' 'NF && $1 != "" {print $1; exit}' "$SUBS" 2>/dev/null)
    if [ -n "$next" ]; then
      echo "$next" > "$ACTIVE"
    else
      : > "$ACTIVE"
    fi
  fi
}
list_subs(){
  active=""; [ -f "$ACTIVE" ] && active=$(cat "$ACTIVE")
  echo -n '{"ok":true,"active":"'
  echo -n "$(json_escape "$active")"
  echo -n '","items":['
  first=1
  while IFS='|' read id name url count updated; do
    [ -z "$id" ] && continue
    [ "$first" = 0 ] && echo -n ','
    first=0
    is_active=false; [ "$id" = "$active" ] && is_active=true
    echo -n "{\"id\":\"$(json_escape "$id")\",\"name\":\"$(json_escape "$name")\",\"url\":\"$(json_escape "$url")\",\"count\":${count:-0},\"updated\":\"$(json_escape "$updated")\",\"active\":$is_active}"
  done < "$SUBS"
  echo ']}'
}

write_config(){
  id="$1"; uuid="$2"; host="$3"; port="$4"; net="$5"; sec="$6"; sni="$7"; fp="$8"; pbk="$9"; sid="${10}"; spx="${11}"; flow="${12}"; service="${13}"; path="${14}"; xmode="${15}"; xhost="${16}"; extra="${17}"; conc="${18}"
  [ -z "$net" ] && net=tcp
  [ -z "$sec" ] && sec=none
  [ -z "$port" ] && port=443
  [ -z "$sni" ] && sni="$host"
  [ -z "$fp" ] && fp=chrome
  [ -z "$spx" ] && spx=/
  flow_line=
  [ -n "$flow" ] && flow_line=",\"flow\":\"$(json_escape "$flow")\""
  stream_extra=
  if [ "$sec" = "reality" ]; then
    stream_extra=",\"realitySettings\":{\"serverName\":\"$(json_escape "$sni")\",\"fingerprint\":\"$(json_escape "$fp")\",\"publicKey\":\"$(json_escape "$pbk")\",\"shortId\":\"$(json_escape "$sid")\",\"spiderX\":\"$(json_escape "$spx")\"}"
  elif [ "$sec" = "tls" ]; then
    stream_extra=",\"tlsSettings\":{\"serverName\":\"$(json_escape "$sni")\",\"fingerprint\":\"$(json_escape "$fp")\"}"
  fi
  if [ "$net" = "grpc" ]; then
    stream_extra="$stream_extra,\"grpcSettings\":{\"serviceName\":\"$(json_escape "$service")\"}"
  fi
  if [ "$net" = "xhttp" ] || [ "$net" = "splithttp" ]; then
    [ -z "$path" ] && path=/
    xhttp="{\"path\":\"$(json_escape "$path")\""
    [ -n "$xmode" ] && [ "$xmode" != "auto" ] && xhttp="$xhttp,\"mode\":\"$(json_escape "$xmode")\""
    [ -n "$xhost" ] && xhttp="$xhttp,\"host\":\"$(json_escape "$xhost")\""
    [ -n "$extra" ] && xhttp="$xhttp,\"extra\":$extra"
    if echo "$conc" | awk 'NF && $0 ~ /^[0-9]+$/ { ok=1 } END { exit ok ? 0 : 1 }'; then
      xhttp="$xhttp,\"scMaxConcurrentPosts\":{\"from\":$conc,\"to\":$conc}"
    fi
    xhttp="$xhttp}"
    stream_extra="$stream_extra,\"xhttpSettings\":$xhttp"
  fi
  cat > "$ROOT/configs/$id.json" <<EOF
{"log":{"loglevel":"info","access":"/var/tmp/vpnui/xray.access.log"},"inbounds":[{"tag":"socks-in","listen":"192.168.0.1","port":1080,"protocol":"socks","settings":{"auth":"noauth","udp":false}},{"tag":"http-in","listen":"192.168.0.1","port":1081,"protocol":"http","settings":{}},{"tag":"redir-in","listen":"0.0.0.0","port":12345,"protocol":"dokodemo-door","settings":{"network":"tcp","followRedirect":true},"sniffing":{"enabled":true,"destOverride":["http","tls"]}}],"outbounds":[{"tag":"vpn-out","protocol":"vless","settings":{"vnext":[{"address":"$(json_escape "$host")","port":$port,"users":[{"id":"$(json_escape "$uuid")","encryption":"none"$flow_line}]}]},"streamSettings":{"network":"$(json_escape "$net")","security":"$(json_escape "$sec")"$stream_extra}},{"tag":"direct","protocol":"freedom"}],"routing":{"domainStrategy":"IPIfNonMatch","rules":[]}}
EOF
}

build_yaml_nodes(){
  out="$BASE/subscription.yaml.nodes"
  awk '
    function trim(s){ gsub(/^[ \t"'"'"']+|[ \t"'"'"',]+$/, "", s); return s }
    function val(line){ sub(/^[^:]*:[ \t]*/, "", line); return trim(line) }
    function reset(){
      name=""; type=""; server=""; port="443"; network="tcp"; uuid="";
      flow=""; tls=""; sni=""; fp="chrome"; pbk=""; sid="";
      service=""; path="/"; inreality=0; ingrpc=0; inws=0; inxhttp=0
    }
    function emit(){
      if (type=="vless" && uuid!="" && server!="" && server!="0.0.0.0" && uuid!="00000000-0000-0000-0000-000000000000") {
        sec=(tls=="true" || pbk!="") ? "reality" : "none"
        gsub(/\|/, "/", name)
        gsub(/\|/, "", server)
        print name "|" uuid "|" server "|" port "|" network "|" sec "|" sni "|" fp "|" pbk "|" sid "|" flow "|" service "|" path
      }
    }
    BEGIN{ reset() }
    /^  - name:/ { emit(); reset(); name=val($0); next }
    /^[ \t]+type:/ { type=val($0); next }
    /^[ \t]+server:/ { server=val($0); next }
    /^[ \t]+port:/ { port=val($0); next }
    /^[ \t]+network:/ { network=val($0); next }
    /^[ \t]+uuid:/ { uuid=val($0); next }
    /^[ \t]+flow:/ { flow=val($0); next }
    /^[ \t]+tls:/ { tls=val($0); next }
    /^[ \t]+servername:/ { sni=val($0); next }
    /^[ \t]+client-fingerprint:/ { fp=val($0); next }
    /^[ \t]+reality-opts:/ { inreality=1; ingrpc=0; inws=0; inxhttp=0; next }
    /^[ \t]+grpc-opts:/ { ingrpc=1; inreality=0; inws=0; inxhttp=0; next }
    /^[ \t]+ws-opts:/ { inws=1; inreality=0; ingrpc=0; inxhttp=0; next }
    /^[ \t]+xhttp-opts:/ { inxhttp=1; inreality=0; ingrpc=0; inws=0; next }
    inreality && /^[ \t]+public-key:/ { pbk=val($0); next }
    inreality && /^[ \t]+short-id:/ { sid=val($0); next }
    ingrpc && /^[ \t]+grpc-service-name:/ { service=val($0); next }
    (inws || inxhttp) && /^[ \t]+path:/ { path=val($0); next }
    END{ emit() }
  ' "$RAW" > "$out"
  [ -s "$out" ] || return 1

  rm -f "$ROOT/configs"/*.json 2>/dev/null
  : > "$ROOT/nodes.txt"
  echo '[' > "$ROOT/nodes.json"
  id=0
  first=1
  while IFS='|' read name uuid host port net sec sni fp pbk sid flow service path; do
    [ -z "$uuid" ] && continue
    [ -z "$host" ] && continue
    [ -z "$name" ] && name="node-$id"
    ipfield=
    is_ip "$host" && ipfield="$host"
    write_config "$id" "$uuid" "$host" "$port" "$net" "$sec" "$sni" "$fp" "$pbk" "$sid" "/" "$flow" "$service" "$path" "" "" "" ""
    echo "$id|node-$id|$host||$ipfield" >> "$ROOT/nodes.txt"
    [ "$first" = 0 ] && echo ',' >> "$ROOT/nodes.json"
    first=0
    ips='[]'
    [ -n "$ipfield" ] && ips="[\"$ipfield\"]"
    printf '{"id":%s,"name":"%s","host":"%s","port":%s,"ips":%s,"ping":null,"network":"%s"}' \
      "$id" "$(json_escape "$name")" "$(json_escape "$host")" "$port" "$ips" "$(json_escape "$net")" >> "$ROOT/nodes.json"
    id=$((id+1))
  done < "$out"
  echo '' >> "$ROOT/nodes.json"
  echo ']' >> "$ROOT/nodes.json"
  [ "$id" -gt 0 ] || return 1
  if [ -d "$USBROOT" ]; then
    mkdir -p "$USBROOT/configs"
    cp -a "$ROOT/nodes.json" "$ROOT/nodes.txt" "$USBROOT/" 2>/dev/null
    rm -f "$USBROOT/configs"/*.json 2>/dev/null
    cp -a "$ROOT/configs"/*.json "$USBROOT/configs/" 2>/dev/null
  fi
  echo "$id"
  return 0
}

build_nodes(){
  : > "$LINKS"
  if ! grep -q 'vless://' "$RAW" 2>/dev/null && grep -q 'data-fetch-url=' "$RAW" 2>/dev/null; then
    rem=$(sed -n 's/.*data-fetch-url="\([^"]*\)".*/\1/p' "$RAW" | head -1)
    if [ -n "$rem" ]; then
      case "$rem" in
        http*) remurl="$rem" ;;
        /*)
          proto=$(echo "$URL" | sed 's#^\(https\?://\).*#\1#')
          host=$(echo "$URL" | sed 's#^https\?://\([^/]*\).*#\1#')
          remurl="$proto$host$rem"
          ;;
        *) remurl="$rem" ;;
      esac
      [ -x "$RWGET" ] && "$RWGET" -U 'Mozilla/5.0' -header 'Accept: application/json,*/*' -O "$RAW" "$remurl" >/dev/null 2>&1 ||
      "$BB" wget --header 'User-Agent: Mozilla/5.0' --header 'Accept: application/json,*/*' -O "$RAW" "$remurl" >/dev/null 2>&1 ||
      "$BB" wget -O "$RAW" "$remurl" >/dev/null 2>&1
    fi
  fi
  if grep -q 'type:[ 	]*vless' "$RAW" 2>/dev/null; then
    build_yaml_nodes
    return $?
  fi
  if grep -q 'vless://' "$RAW" 2>/dev/null; then
    tr '\r",' '\n' < "$RAW" | "$BB" grep -o 'vless://[^[:space:]]*' > "$LINKS"
  else
    {
      echo 'begin-base64 644 /tmp/subscription.dec'
      cat "$RAW"
      echo '===='
    } > "$BASE/subscription.uue"
    "$BB" uudecode -o "$BASE/subscription.dec" "$BASE/subscription.uue" 2>/dev/null || true
    tr '\r",' '\n' < "$BASE/subscription.dec" 2>/dev/null | "$BB" grep -o 'vless://[^[:space:]]*' > "$LINKS"
  fi
  [ -s "$LINKS" ] || return 1

  rm -f "$ROOT/configs"/*.json 2>/dev/null
  : > "$ROOT/nodes.txt"
  echo '[' > "$ROOT/nodes.json"
  id=0
  first=1
  while read line; do
    echo "$line" | grep -q '^vless://' || continue
    line=$(urldecode "$line")
    main=${line#vless://}
    frag=
    case "$main" in *#*) frag=${main#*#}; main=${main%%#*};; esac
    query=
    case "$main" in *\?*) query=${main#*\?}; main=${main%%\?*};; esac
    [ "$main" = "${main#*@}" ] && continue
    uuid=${main%@*}
    hp=${main#*@}
    host=${hp%%:*}
    port=${hp#*:}
    [ "$host" = "$hp" ] && port=443
    host=$(echo "$host" | sed 's/^<//;s/>$//;s/^\[//;s/\]$//')
    [ -z "$uuid" ] && continue
    [ -z "$host" ] && continue
    net=$(qget "$query" type); [ -z "$net" ] && net=tcp
    sec=$(qget "$query" security); [ -z "$sec" ] && sec=none
    sni=$(qget "$query" sni); [ -z "$sni" ] && sni=$(qget "$query" serverName)
    fp=$(qget "$query" fp)
    pbk=$(qget "$query" pbk)
    sid=$(qget "$query" sid)
    spx=$(qget "$query" spx)
    flow=$(qget "$query" flow)
    service=$(qget "$query" serviceName)
    path=$(qget "$query" path)
    xmode=$(qget "$query" mode)
    xhost=$(qget "$query" host)
    [ -z "$xhost" ] && xhost=$(qget "$query" authority)
    extra=$(qget "$query" extra)
    conc=$(qget "$query" concurrency)
    name=$(urldecode "$frag")
    [ -z "$name" ] && name="node-$id"
    [ "$name" = "App not supported" ] && continue
    [ "$host" = "SERVER_IP" ] && continue
    [ "$host" = "server_ip" ] && continue
    [ "$host" = "0.0.0.0" ] && continue
    [ "$host" = "127.0.0.1" ] && continue
    [ "$port" = "1" ] && continue
    [ "$uuid" = "00000000-0000-0000-0000-000000000000" ] && continue
    ipfield=
    is_ip "$host" && ipfield="$host"

    write_config "$id" "$uuid" "$host" "$port" "$net" "$sec" "$sni" "$fp" "$pbk" "$sid" "$spx" "$flow" "$service" "$path" "$xmode" "$xhost" "$extra" "$conc"
    echo "$id|node-$id|$host||$ipfield" >> "$ROOT/nodes.txt"
    [ "$first" = 0 ] && echo ',' >> "$ROOT/nodes.json"
    first=0
    ips='[]'
    [ -n "$ipfield" ] && ips="[\"$ipfield\"]"
    printf '{"id":%s,"name":"%s","host":"%s","port":%s,"ips":%s,"ping":null,"network":"%s"}' \
      "$id" "$(json_escape "$name")" "$(json_escape "$host")" "$port" "$ips" "$(json_escape "$net")" >> "$ROOT/nodes.json"
    id=$((id+1))
  done < "$LINKS"
  echo '' >> "$ROOT/nodes.json"
  echo ']' >> "$ROOT/nodes.json"
  [ "$id" -gt 0 ] || return 1
  if [ -d "$USBROOT" ]; then
    mkdir -p "$USBROOT/configs"
    cp -a "$ROOT/nodes.json" "$ROOT/nodes.txt" "$USBROOT/" 2>/dev/null
    rm -f "$USBROOT/configs"/*.json 2>/dev/null
    cp -a "$ROOT/configs"/*.json "$USBROOT/configs/" 2>/dev/null
  fi
  echo "$id"
  return 0
}

case "$ACTION" in
  save|update|select)
    ID=$(safe_id "$ID")
    if [ "$ACTION" = "update" ] || [ "$ACTION" = "select" ]; then
      if [ -n "$ID" ]; then
        oldurl=$(sub_url_by_id "$ID")
        oldname=$(sub_name_by_id "$ID")
        [ -z "$URL" ] && URL="$oldurl"
        [ -z "$NAME" ] && NAME="$oldname"
      fi
    fi
    if [ -z "$URL" ]; then
      echo '{"ok":false,"message":"empty url","count":0}'
      exit 0
    fi
    rm -f "$RAW"
    if is_direct_vless "$URL"; then
      printf '%s\n' "$URL" > "$RAW"
    else
      [ -x "$RWGET" ] && "$RWGET" -U 'v2RayTun/6.0' -header 'Accept: */*' -header 'x-hwid: router-vpn-5200293391' -header 'x-device-os: Router' -header 'x-device-model: RT-GM2-9' -header 'x-ver-os: 3.18.21' -O "$RAW" "$URL" >/dev/null 2>&1 ||
      [ -x "$RWGET" ] && "$RWGET" -U 'Happ/1.0.0' -header 'Accept: */*' -header 'x-hwid: router-vpn-5200293391' -header 'x-device-os: Router' -header 'x-device-model: RT-GM2-9' -header 'x-ver-os: 3.18.21' -O "$RAW" "$URL" >/dev/null 2>&1 ||
      [ -x "$RWGET" ] && "$RWGET" -U 'FlClashX/0.8.83' -header 'Accept: */*' -header 'x-hwid: router-vpn-5200293391' -header 'x-device-os: Router' -header 'x-device-model: RT-GM2-9' -header 'x-ver-os: 3.18.21' -O "$RAW" "$URL" >/dev/null 2>&1 ||
      "$BB" wget --header 'User-Agent: v2RayTun/6.0' --header 'Accept: */*' --header 'x-hwid: router-vpn-5200293391' --header 'x-device-os: Router' --header 'x-device-model: RT-GM2-9' --header 'x-ver-os: 3.18.21' -O "$RAW" "$URL" >/dev/null 2>&1 ||
      "$BB" wget --header 'User-Agent: Happ/1.0.0' --header 'Accept: */*' --header 'x-hwid: router-vpn-5200293391' --header 'x-device-os: Router' --header 'x-device-model: RT-GM2-9' --header 'x-ver-os: 3.18.21' -O "$RAW" "$URL" >/dev/null 2>&1 ||
      "$BB" wget --header 'User-Agent: FlClashX/0.8.83' --header 'Accept: */*' --header 'x-hwid: router-vpn-5200293391' --header 'x-device-os: Router' --header 'x-device-model: RT-GM2-9' --header 'x-ver-os: 3.18.21' -O "$RAW" "$URL" >/dev/null 2>&1 ||
      "$BB" wget --user-agent 'ClashforWindows/0.20.39' -O "$RAW" "$URL" >/dev/null 2>&1 ||
      "$BB" wget -U 'ClashforWindows/0.20.39' -O "$RAW" "$URL" >/dev/null 2>&1 ||
      "$BB" wget --header 'User-Agent: ClashforWindows/0.20.39' --header 'Accept: */*' -O "$RAW" "$URL" >/dev/null 2>&1 ||
      "$BB" wget --user-agent 'Clash.Meta' -O "$RAW" "$URL" >/dev/null 2>&1 ||
      "$BB" wget -O "$RAW" "$URL" >/dev/null 2>&1
    fi
    if [ ! -s "$RAW" ]; then
      echo '{"ok":false,"message":"download failed","count":0}'
      exit 0
    fi
    if grep -q 'App not supported' "$RAW" 2>/dev/null || grep -q 'x-hwid-not-supported' "$RAW" 2>/dev/null; then
      echo '{"ok":false,"message":"provider returned App not supported / HWID locked config","count":0}'
      exit 0
    fi
    if grep -q 'proxies:[ 	]*\[\]' "$RAW" 2>/dev/null; then
      echo '{"ok":false,"message":"subscription downloaded, but provider returned zero proxies","count":0}'
      exit 0
    fi
    count=$(build_nodes)
    if [ -n "$count" ] && [ "$count" -gt 0 ] 2>/dev/null; then
      [ -z "$ID" ] && ID=$(new_id)
      upsert_sub "$ID" "$NAME" "$URL" "$count"
      echo "{\"ok\":true,\"message\":\"saved, $count servers loaded\",\"count\":$count,\"id\":\"$(json_escape "$ID")\"}"
    else
      if grep -q '<SERVER_IP>\|SERVER_IP\|server_ip' "$RAW" 2>/dev/null; then
        echo '{"ok":false,"message":"vless link contains SERVER_IP placeholder; paste a real server address","count":0}'
      else
        echo '{"ok":false,"message":"no supported vless links found","count":0}'
      fi
    fi
    ;;
  delete)
    delete_sub "$ID"
    list_subs
    ;;
  list)
    list_subs
    ;;
  status|*)
    u=""; [ -f "$URLFILE" ] && u=$(json_escape "$(cat "$URLFILE")")
    count=0; [ -f "$ROOT/nodes.txt" ] && count=$(wc -l < "$ROOT/nodes.txt")
    active=""; [ -f "$ACTIVE" ] && active=$(json_escape "$(cat "$ACTIVE")")
    echo "{\"ok\":true,\"url\":\"$u\",\"count\":$count,\"active\":\"$active\"}"
    ;;
esac
