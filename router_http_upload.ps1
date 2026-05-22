param(
    [string]$Router = "192.168.0.1",
    [string]$User = "superadmin",
    [int]$Port = 8099
)

$ErrorActionPreference = "Stop"
$Base = Split-Path -Parent $MyInvocation.MyCommand.Path
$Site = Join-Path $Base "vpnui\site"
if (!(Test-Path (Join-Path $Site "index.html"))) {
    throw "Site folder not found: $Site"
}

function Find-Python {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $cmd = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "Python is required for the temporary HTTP server."
}

function Get-LocalIpForRouter {
    $udp = [Net.Sockets.UdpClient]::new()
    try {
        $udp.Connect($Router, 8083)
        return $udp.Client.LocalEndPoint.Address.ToString()
    } finally {
        $udp.Dispose()
    }
}

$Python = Find-Python
$LocalIp = Get-LocalIpForRouter
$BaseUrl = "http://$LocalIp`:$Port"

Write-Host "Serving $Site at $BaseUrl/"
$Server = Start-Process -FilePath $Python -ArgumentList @("-m", "http.server", "$Port", "--bind", "0.0.0.0", "--directory", "$Site") -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 1

$Remote = @'
set -e
BASE=/var/tmp/vpnui
ROOT=$BASE/www
USB=/var/usbmnt/sda1/vpnui
USBROOT=$USB/www
BB=$BASE/bin/busybox-mips
URL="__BASE_URL__"

mkdir -p /var/usbmnt/sda1 "$BASE/bin" "$ROOT" "$USBROOT"
mount | grep '/var/usbmnt/sda1' >/dev/null 2>&1 || mount -t ext2 /dev/sda1 /var/usbmnt/sda1
[ -x "$BB" ] || cp "$USB/bin/busybox-mips" "$BB" 2>/dev/null || true
chmod +x "$BB" 2>/dev/null || true

fetch(){
  src="$1"
  dst="$2"
  tmp="$dst.tmp"
  mkdir -p "$(dirname "$dst")"
  if [ -x "$BASE/bin/rwget" ]; then
    "$BASE/bin/rwget" -O "$tmp" "$URL/$src"
  elif [ -x "$USB/bin/rwget" ]; then
    "$USB/bin/rwget" -O "$tmp" "$URL/$src"
  else
    "$BB" wget -O "$tmp" "$URL/$src"
  fi
  mv "$tmp" "$dst"
}

copy_one(){
  rel="$1"
  fetch "$rel" "$ROOT/$rel"
  fetch "$rel" "$USBROOT/$rel"
}

copy_one index.html
copy_one nodes.json
copy_one nodes.txt
for f in \
  cgi-bin/subscription.cgi \
  cgi-bin/system.cgi \
  cgi-bin/ping.cgi \
  cgi-bin/selective.cgi \
  cgi-bin/info.cgi \
  cgi-bin/rules.cgi \
  cgi-bin/vpn.cgi \
  cgi-bin/dns.cgi \
  cgi-bin/traffic.cgi \
  cgi-bin/devices.cgi \
  cgi-bin/auto.cgi
do
  copy_one "$f"
done

mkdir -p "$ROOT/assets/flags" "$USBROOT/assets/flags"
if [ -x "$BASE/bin/rwget" ]; then
  "$BASE/bin/rwget" -O /tmp/router-vpn-flags.txt "$URL/assets/flags/flags.txt"
elif [ -x "$USB/bin/rwget" ]; then
  "$USB/bin/rwget" -O /tmp/router-vpn-flags.txt "$URL/assets/flags/flags.txt"
else
  "$BB" wget -O /tmp/router-vpn-flags.txt "$URL/assets/flags/flags.txt"
fi
while read flag; do
  [ -z "$flag" ] && continue
  copy_one "assets/flags/$flag"
done < /tmp/router-vpn-flags.txt

chmod +x "$ROOT/cgi-bin/"*.cgi "$USBROOT/cgi-bin/"*.cgi 2>/dev/null || true
ps | grep '/var/tmp/vpnui/bin/busybox-mips httpd' | grep -v grep | awk '{print $1}' | while read pid; do kill -9 "$pid" 2>/dev/null || true; done
"$BB" httpd -f -p 192.168.0.1:8083 -h "$ROOT" >/var/tmp/vpnui/httpd.log 2>&1 &
iptables -C INPUT -i br2 -p tcp --dport 8083 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -i br2 -p tcp --dport 8083 -j ACCEPT
echo OK
'@.Replace("__BASE_URL__", $BaseUrl)

try {
    $FlagDir = Join-Path $Site "assets\flags"
    Get-ChildItem -Path $FlagDir -Filter "*.svg" | Sort-Object Name | ForEach-Object { $_.Name } | Set-Content -LiteralPath (Join-Path $FlagDir "flags.txt") -Encoding ASCII
    Write-Host "Uploading through router wget. Enter SSH password if prompted."
    $Remote | ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL "$User@$Router" "sh -s"
    if ($LASTEXITCODE -ne 0) { throw "Remote upload command failed." }
    Write-Host "Done: http://$Router`:8083/"
} finally {
    if ($Server -and !$Server.HasExited) {
        Stop-Process -Id $Server.Id -Force
    }
}
