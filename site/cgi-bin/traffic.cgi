#!/bin/bash
# traffic.cgi -- expose live traffic stats from xray access log + system.
#
#   action=stats               -- bytes RX/TX + open connection count (default)
#   action=destinations[&minutes=60][&limit=30]
#                              -- top destination hosts in last <minutes>
#   action=recent[&limit=80]   -- last N access-log lines, parsed
#   action=connections[&limit=80]
#                              -- snapshot of established outgoing connections
#   action=log[&lines=200]     -- raw xray error log (debug)

set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib.sh"

parse_query
ACTION=${QPARAM[action]:-stats}
ACCESS_LOG=${WISD_LOG_DIR:-/var/log/wisd}/access.log
ERROR_LOG=${WISD_LOG_DIR:-/var/log/wisd}/xray.log

json_header

case "$ACTION" in
    stats)
        # System-wide TX/RX on the primary uplink (non-lo) interface.
        rx=0; tx=0; iface=""
        if [[ -r /proc/net/dev ]]; then
            iface_line=$(awk 'NR>2 && $1!~"^lo:" {gsub(":","",$1); print $1" "$2" "$10; exit}' /proc/net/dev)
            iface=$(awk '{print $1}' <<<"$iface_line")
            rx=$(awk '{print $2}' <<<"$iface_line")
            tx=$(awk '{print $3}' <<<"$iface_line")
        fi
        # xray pid + memory + uptime
        pid=$(pgrep -x xray | head -1)
        rss_kb=0; uptime_s=0
        if [[ -n "$pid" && -r "/proc/$pid/status" ]]; then
            rss_kb=$(awk '/VmRSS/{print $2}' "/proc/$pid/status")
            start_clk=$(awk '{print $22}' "/proc/$pid/stat")
            clk_tck=$(getconf CLK_TCK 2>/dev/null || echo 100)
            btime=$(awk '/btime/{print $2}' /proc/stat)
            if [[ -n "$start_clk" && -n "$btime" ]]; then
                start_s=$(( btime + start_clk / clk_tck ))
                uptime_s=$(( $(date +%s) - start_s ))
            fi
        fi
        # connections: established outgoing (excluding loopback)
        established=$(ss -tnH state established 2>/dev/null | wc -l)
        udp_active=$(ss -unH 2>/dev/null | wc -l)
        cat <<JSON
{
  "ok": true,
  "iface": "$(json_escape "${iface:-?}")",
  "rxBytes": ${rx:-0},
  "txBytes": ${tx:-0},
  "establishedTCP": ${established:-0},
  "activeUDP": ${udp_active:-0},
  "xray": {
    "pid": ${pid:-0},
    "rssBytes": $(( ${rss_kb:-0} * 1024 )),
    "uptimeSec": ${uptime_s:-0}
  },
  "timestamp": $(date +%s)
}
JSON
        ;;

    destinations)
        MINUTES=${QPARAM[minutes]:-60}
        LIMIT=${QPARAM[limit]:-30}
        [[ "$MINUTES" =~ ^[0-9]+$ ]] || MINUTES=60
        [[ "$LIMIT" =~ ^[0-9]+$ ]] || LIMIT=30
        (( MINUTES > 1440 )) && MINUTES=1440
        (( LIMIT > 200 )) && LIMIT=200

        WISD_AC=$ACCESS_LOG WISD_MIN="$MINUTES" WISD_LIM="$LIMIT" python3 - <<'PY'
import os, re, sys, json, time
from collections import defaultdict

LOG = os.environ['WISD_AC']
MIN = int(os.environ['WISD_MIN'])
LIM = int(os.environ['WISD_LIM'])
cutoff = time.time() - MIN * 60

# Format: 2026/05/24 10:53:41 from <src> accepted [//]<proto:>?<host>:<port> [<inbound> -> <outbound>]
# Examples:
#   2026/05/24 10:58:47 from tcp:100.23.34.160:25880 accepted tcp:172.66.147.243:443 [socks-in -> direct]
#   2026/05/24 10:59:12 from tcp:100.23.34.160:25400 accepted tcp:www.google.com:443 [socks-in -> direct]
#   2026/05/24 10:53:41 from 37.49.224.127:46098 accepted //vmpprota.biz:4443 [http-in -> direct]
LINE = re.compile(
    r'^(?P<ts>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) from (?P<src>\S+) '
    r'(?P<verdict>accepted|rejected) +(?P<dest>\S+) '
    r'\[(?P<inb>[\w-]+) (?:-+>|>>) (?P<outb>[\w-]+)\]'
)
DEST = re.compile(r'^(?:(?P<proto>tcp|udp):|//)?(?P<host>\[[0-9a-f:]+\]|[^:]+)(?::(?P<port>\d+))?$')

counts = defaultdict(int)
last = {}
inb_of = {}
src_of = defaultdict(set)
total = 0
recent = 0

try:
    with open(LOG, 'rb') as f:
        try:
            f.seek(-2_000_000, os.SEEK_END)  # only tail
        except OSError:
            f.seek(0)
        f.readline()  # skip partial first line
        for raw in f:
            try:
                line = raw.decode('utf-8', 'ignore').rstrip()
            except Exception:
                continue
            m = LINE.match(line)
            if not m:
                continue
            total += 1
            try:
                t = time.mktime(time.strptime(m['ts'], '%Y/%m/%d %H:%M:%S'))
            except Exception:
                continue
            if t < cutoff:
                continue
            recent += 1
            if m['verdict'] != 'accepted':
                continue
            dm = DEST.match(m['dest'])
            if not dm:
                continue
            host = dm['host'].strip('[]')
            port = dm['port'] or ''
            key = f"{host}:{port}" if port else host
            counts[key] += 1
            last[key] = m['ts']
            inb_of[key] = m['inb']
            src = m['src'].split(':')[1] if ':' in m['src'] else m['src']
            src_of[key].add(src)
except FileNotFoundError:
    pass

rows = []
for k, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:LIM]:
    host, _, port = k.partition(':')
    rows.append({
        'host': host,
        'port': int(port) if port.isdigit() else 0,
        'count': n,
        'lastTs': last.get(k, ''),
        'inbound': inb_of.get(k, ''),
        'uniqueClients': len(src_of.get(k, ())),
    })

print(json.dumps({
    'ok': True,
    'minutes': MIN,
    'limit': LIM,
    'totalLinesScanned': total,
    'totalRecent': recent,
    'rows': rows,
}, ensure_ascii=False))
PY
        ;;

    recent)
        LIMIT=${QPARAM[limit]:-80}
        [[ "$LIMIT" =~ ^[0-9]+$ ]] || LIMIT=80
        (( LIMIT > 500 )) && LIMIT=500
        WISD_AC=$ACCESS_LOG WISD_LIM="$LIMIT" python3 - <<'PY'
import os, re, json, subprocess
LOG = os.environ['WISD_AC']
LIM = int(os.environ['WISD_LIM'])
LINE = re.compile(
    r'^(?P<ts>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) from (?P<src>\S+) '
    r'(?P<verdict>accepted|rejected) +(?P<dest>\S+) '
    r'\[(?P<inb>[\w-]+) (?:-+>|>>) (?P<outb>[\w-]+)\]'
)
items = []
try:
    raw = subprocess.check_output(['tail', '-n', str(LIM * 3), LOG], text=True, errors='ignore')
except Exception:
    raw = ''
for line in raw.splitlines():
    m = LINE.match(line)
    if not m:
        continue
    items.append({
        'ts': m['ts'],
        'src': m['src'],
        'verdict': m['verdict'],
        'dest': m['dest'],
        'inbound': m['inb'],
        'outbound': m['outb'],
    })
items = items[-LIM:]
print(json.dumps({'ok': True, 'items': items}, ensure_ascii=False))
PY
        ;;

    connections)
        LIMIT=${QPARAM[limit]:-80}
        [[ "$LIMIT" =~ ^[0-9]+$ ]] || LIMIT=80
        (( LIMIT > 500 )) && LIMIT=500
        WISD_LIM="$LIMIT" python3 - <<'PY'
import os, json, subprocess, re
LIM = int(os.environ['WISD_LIM'])
# ss -tnp shows process info, but only as root for non-self. We're running as
# www-data via fcgiwrap, so process names will likely be hidden. Still useful.
out = subprocess.check_output(['ss', '-tnH', 'state', 'established'], text=True, errors='ignore')
rows = []
for line in out.splitlines()[:LIM*3]:
    parts = line.split()
    if len(parts) < 5:
        continue
    local = parts[3]
    peer = parts[4]
    rows.append({'local': local, 'peer': peer})
# Sort by peer (so same destination groups together)
rows.sort(key=lambda r: r['peer'])
print(json.dumps({'ok': True, 'rows': rows[:LIM], 'totalEstablished': len(rows)}, ensure_ascii=False))
PY
        ;;

    log)
        LINES=${QPARAM[lines]:-200}
        [[ "$LINES" =~ ^[0-9]+$ ]] || LINES=200
        (( LINES > 2000 )) && LINES=2000
        if [[ -f "$ERROR_LOG" ]]; then
            content=$(tail -n "$LINES" "$ERROR_LOG")
        else
            content=""
        fi
        python3 -c "import json,sys; print(json.dumps({'ok':True,'log':sys.stdin.read()}, ensure_ascii=False))" <<<"$content"
        ;;

    *)
        json_error 12 "unknown action: $ACTION"
        ;;
esac
