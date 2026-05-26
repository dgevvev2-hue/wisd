#!/bin/bash
# info.cgi -- read-only system / VPS info.
DIR=$(dirname "$0")
. "$DIR/lib.sh"

json_header

hostname=$(json_escape "$(hostname 2>/dev/null || echo unknown)")
kernel=$(json_escape "$(uname -r 2>/dev/null)")
osname=$(json_escape "$(. /etc/os-release 2>/dev/null; echo "$PRETTY_NAME")")
uptime_s=$(uptime_now)
ip4=$(json_escape "$(curl -s --max-time 2 https://ifconfig.io 2>/dev/null || echo '')")
[[ -z "$ip4" ]] && ip4=$(json_escape "$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | head -1 | cut -d/ -f1)")
load=$(json_escape "$(cut -d ' ' -f 1-3 /proc/loadavg 2>/dev/null)")
mem_total=$(awk '/^MemTotal/{print $2; exit}' /proc/meminfo 2>/dev/null)
mem_avail=$(awk '/^MemAvailable/{print $2; exit}' /proc/meminfo 2>/dev/null)
disk_line=$(df -kP / 2>/dev/null | awk 'NR==2 {print $2","$3","$4}')

xray_pid=$(pgrep -x xray | head -1)
running=false
[[ -n "$xray_pid" ]] && running=true

cat <<JSON
{
  "ok": true,
  "host": "$hostname",
  "kernel": "$kernel",
  "os": "$osname",
  "uptime": $uptime_s,
  "ip4": "$ip4",
  "load": "$load",
  "memTotalKb": ${mem_total:-0},
  "memAvailKb": ${mem_avail:-0},
  "disk": "$disk_line",
  "xrayRunning": $running,
  "xrayPid": "${xray_pid:-}"
}
JSON
