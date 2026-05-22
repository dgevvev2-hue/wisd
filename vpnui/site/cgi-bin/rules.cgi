#!/var/tmp/vpnui/bin/busybox-mips ash
BASE=/var/tmp/vpnui
STORE=/var/LxC
RULES=$STORE/rules.txt
ACTION=list
VALUE=
urldecode(){ v=$(echo "$1" | sed 's/+/ /g;s/%/\\x/g'); printf '%b' "$v"; }
for p in $(echo "$QUERY_STRING" | tr '&' ' '); do
  k=${p%%=*}; v=${p#*=}; v=$(urldecode "$v")
  [ "$k" = "action" ] && ACTION=$v
  [ "$k" = "value" ] && VALUE=$v
done
safe_value(){ echo "$1" | tr -cd 'A-Za-z0-9*._:-'; }
has_rule(){ awk -v v="$1" '$0 == v { found=1 } END { exit found ? 0 : 1 }' "$RULES" 2>/dev/null; }
dedupe_rules(){
  awk 'NF && !seen[$0]++ { print $0 }' "$RULES" > "$RULES.tmp" 2>/dev/null
  mv "$RULES.tmp" "$RULES"
}
add_rule(){
  v=$(safe_value "$1")
  [ -n "$v" ] && ! has_rule "$v" && echo "$v" >> "$RULES"
}
delete_rule(){
  v=$(safe_value "$1")
  [ -z "$v" ] && return 0
  awk -v v="$v" '$0 != v { print }' "$RULES" > "$RULES.tmp" 2>/dev/null
  mv "$RULES.tmp" "$RULES"
}
add_ru_preset(){
  for v in \
    sberbank.ru online.sberbank.ru sberbank.com sber.ru tinkoff.ru tinkoffbank.ru tinkoffinsurance.ru \
    vtb.ru online.vtb.ru gazprombank.ru gpbl.ru alfabank.ru click.alfabank.ru open.ru banki.ru \
    raiffeisen.ru pochtabank.ru sovcombank.ru halvacard.ru mkb.ru psbank.ru rshb.ru domrfbank.ru \
    rncb.ru rosbank.ru otpbank.ru otpbank.ru citibank.ru akbars.ru bcs.ru finam.ru moex.com moex.ru \
    mironline.ru privetmir.ru nspk.ru sbp.nspk.ru qiwi.com yoomoney.ru yoo.money paykeeper.ru cloudpayments.ru \
    gosuslugi.ru esia.gosuslugi.ru nalog.gov.ru lkfl2.nalog.ru fns.ru mos.ru mosreg.ru pochta.ru \
    yandex.ru ya.ru yastatic.net yandex.net yandex.st yandexcloud.net yandexcdn.net yandex-team.ru yandexbank.ru \
    yoomoney.ru music.yandex.ru music.yandex.net api.music.yandex.net radio.yandex.ru plus.yandex.ru passport.yandex.ru \
    oauth.yandex.ru login.yandex.ru mc.yandex.ru metrika.yandex.ru clck.yandex.ru suggest.yandex.ru browser.yandex.ru \
    market.yandex.ru taxi.yandex.ru maps.yandex.ru disk.yandex.ru mail.yandex.ru kinopoisk.ru hd.kinopoisk.ru \
    strm.yandex.ru yandexvideo.net yandexvideocdn.net \
    kion.ru kioncdn.ru cdn.kion.ru api.kion.ru media.kion.ru tv.kion.ru mts.ru lk.mts.ru login.mts.ru payment.mts.ru \
    static.mts.ru stream.mts.ru iptv.mts.ru mtstv.ru mts-cdn.ru \
    ozon.ru ozonusercontent.com wildberries.ru wb.ru static-basket-01.wb.ru avito.ru cdek.ru 2gis.ru dgis.ru \
    rutube.ru vk.com vk.ru mail.ru ok.ru mycdn.me kaspersky.ru drweb.ru mts.ru megafon.ru beeline.ru tele2.ru; do
    add_rule "$v"
  done
}
json_list(){
  echo -n '{"rules":['
  first=1
  if [ -f "$RULES" ]; then
    while read r; do
      [ -z "$r" ] && continue
      [ "$first" = 0 ] && echo -n ','
      first=0
      r=$(echo "$r" | sed 's/\\/\\\\/g;s/"/\\"/g')
      echo -n "\"$r\""
    done < "$RULES"
  fi
  echo ']}'
}
mkdir -p "$BASE"
touch "$RULES"
case "$ACTION" in
  add)
    add_rule "$VALUE"
    ;;
  delete)
    delete_rule "$VALUE"
    ;;
  preset_ru)
    add_ru_preset
    ;;
esac
dedupe_rules
printf 'Content-Type: application/json; charset=utf-8\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'
json_list
