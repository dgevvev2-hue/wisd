from pathlib import Path

root = Path(__file__).resolve().parent
out = root / "router_collect_diagnostics.bat"

payload = r'''
$ErrorActionPreference = 'Stop'
$Base = Split-Path -Parent $env:SELF
$Work = Join-Path $env:TEMP ('router-diag-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $Work | Out-Null

function Test-Python { param([string]$Path)
    if (!$Path -or !(Test-Path $Path)) { return $false }
    if ($Path -like '*\WindowsApps\python.exe' -or $Path -like '*\WindowsApps\python3.exe') { return $false }
    try { & $Path -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' 2>$null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}
function Install-LocalPython {
    $LocalPython = Join-Path $Base 'python\python.exe'
    if (Test-Python $LocalPython) { return $LocalPython }
    Write-Host 'Real Python not found. Downloading Python installer...'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $Installer = Join-Path $Base 'python-installer.exe'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile $Installer
    Write-Host 'Installing local Python near this BAT...'
    $Target = Join-Path $Base 'python'
    Start-Process -FilePath $Installer -Wait -ArgumentList @('/quiet','InstallAllUsers=0','PrependPath=0','Include_launcher=0','Include_pip=1','Include_test=0','SimpleInstall=1',"TargetDir=$Target")
    if (!(Test-Python $LocalPython)) { throw 'Local Python install failed.' }
    return $LocalPython
}
function Find-Python {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Python $cmd.Source)) { return $cmd.Source }
    $cmd = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Python $cmd.Source)) { return $cmd.Source }
    foreach ($p in @((Join-Path $Base 'python\python.exe'), "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe", 'C:\Python312\python.exe', 'C:\Python311\python.exe', 'C:\Python310\python.exe', 'C:\Program Files\Python312\python.exe', 'C:\Program Files\Python311\python.exe', 'C:\Program Files\Python310\python.exe')) {
        if ($p -and (Test-Python $p)) { return $p }
    }
    return (Install-LocalPython)
}
$Python = Find-Python
Write-Host "Using Python: $Python"
$ParamikoOk = $false
try { & $Python -c "import paramiko, sys; sys.exit(0 if paramiko.__version__ == '3.5.1' else 1)" 2>$null; $ParamikoOk = ($LASTEXITCODE -eq 0) } catch { $ParamikoOk = $false }
if (!$ParamikoOk) {
    Write-Host 'Installing compatible Paramiko...'
    & $Python -m pip install --user --force-reinstall 'paramiko==3.5.1'
    if ($LASTEXITCODE -ne 0) { throw 'Paramiko install failed. Check internet connection.' }
}

$PyFile = Join-Path $Work 'diag.py'
$PyCode = @'
import json, socket, time, urllib.request
from datetime import datetime
from pathlib import Path
import paramiko

HOST='192.168.0.1'; USER='superadmin'; PASSWORD='8WHoDt3yCQR98BRx'
last_run=0.0

def prefer(sec, name, wanted):
    if not hasattr(sec,name): return
    cur=list(getattr(sec,name)); out=[x for x in wanted if x in cur]+[x for x in cur if x not in wanted]
    if out: setattr(sec,name,out)
def open_client():
    sock=socket.create_connection((HOST,22),timeout=15)
    t=paramiko.Transport(sock); sec=t.get_security_options()
    prefer(sec,'kex',['diffie-hellman-group1-sha1','diffie-hellman-group14-sha1'])
    prefer(sec,'key_types',['ssh-rsa'])
    prefer(sec,'ciphers',['aes128-cbc','3des-cbc','aes256-cbc','aes128-ctr'])
    prefer(sec,'digests',['hmac-sha1','hmac-sha1-96','hmac-md5'])
    t.start_client(timeout=20); t.auth_password(USER,PASSWORD)
    if not t.is_authenticated(): raise RuntimeError('SSH password auth failed')
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy()); c._transport=t
    return c
def run_ssh(cmd, timeout=20, tries=4):
    global last_run
    err=None
    for attempt in range(tries):
        wait=0.5 + attempt*0.8 - (time.time()-last_run)
        if wait>0: time.sleep(wait)
        c=None
        try:
            c=open_client(); _,stdout,_=c.exec_command(cmd+' 2>&1',timeout=timeout)
            ch=stdout.channel; ch.settimeout(0.3); buf=b''; end=time.time()+timeout
            while time.time()<end:
                try:
                    if ch.recv_ready(): buf += ch.recv(4096)
                except socket.timeout: pass
                if ch.exit_status_ready():
                    while ch.recv_ready(): buf += ch.recv(4096)
                    break
                time.sleep(0.1)
            try: ch.close()
            except Exception: pass
            last_run=time.time()
            return buf.decode('utf-8','replace')
        except Exception as e:
            err=e; last_run=time.time(); time.sleep(1.2)
        finally:
            try:
                if c: c.close()
            except Exception: pass
    return 'ERROR: %r' % (err,)

def http_get(url):
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data=r.read(8000)
        return data.decode('utf-8','replace')
    except Exception as e:
        return 'HTTP ERROR: %r' % (e,)

sections=[
('whoami_uname_date', 'id; uname -a; date; uptime; cat /proc/uptime 2>/dev/null'),
('mount_df', 'mount; echo ---; df -h; echo ---; ls -la /var/usbmnt /var/usbmnt/sda1 /var/usbmnt/sda1/vpnui 2>/dev/null'),
('processes', 'ps | grep -E \"xray|httpd|busybox-mips|dropbear\" | grep -v grep'),
('vpn_files', 'ls -l /var/tmp/xray /var/tmp/vpnui /var/tmp/vpnui/www /var/tmp/vpnui/www/cgi-bin /var/tmp/vpnui/www/configs 2>/dev/null | head -120'),
('nodes_counts', 'echo nodes_json=$(wc -c /var/tmp/vpnui/www/nodes.json 2>/dev/null); echo nodes_txt=$(wc -l /var/tmp/vpnui/www/nodes.txt 2>/dev/null); echo configs=$(ls /var/tmp/vpnui/www/configs/*.json 2>/dev/null | wc -l); head -5 /var/tmp/vpnui/www/nodes.txt 2>/dev/null'),
('state_files', 'for f in /var/tmp/vpnui/state /var/tmp/vpnui/mode /var/tmp/vpnui/started_at /var/tmp/vpnui/xray.pid /var/LxC/vpnui.state /var/LxC/vpnui.mode /var/LxC/vpnui.autostart /var/LxC/subscription.url; do echo ---$f; cat $f 2>/dev/null; done'),
('xray_log_tail', 'echo --- xray.log; tail -80 /var/tmp/vpnui/xray.log 2>/dev/null; echo --- access; tail -40 /var/tmp/vpnui/xray.access.log 2>/dev/null'),
('iptables_nat', 'iptables -t nat -S 2>/dev/null | grep -E \"XRAY|12345|1080|1081\" || true; echo --- filter; iptables -S 2>/dev/null | grep -E \"8083|1080|1081|12345|XRAY\" || true'),
('active_json_head', 'echo active_size=$(wc -c /var/tmp/vpnui/active.json 2>/dev/null); head -80 /var/tmp/vpnui/active.json 2>/dev/null'),
('network_dns', 'cat /etc/resolv.conf 2>/dev/null; echo --- routes; route -n 2>/dev/null; echo --- ping; ping -c 2 1.1.1.1 2>&1; ping -c 2 your-durev.com 2>&1'),
]

report=[]
report.append('ROUTER DIAGNOSTICS ' + datetime.now().isoformat(timespec='seconds'))
report.append('Target: %s' % HOST)
report.append('')
report.append('===== HTTP status.cgi =====')
report.append(http_get('http://192.168.0.1:8083/cgi-bin/vpn.cgi?action=status'))
report.append('')
report.append('===== HTTP nodes.json head =====')
report.append(http_get('http://192.168.0.1:8083/nodes.json')[:2000])
for title,cmd in sections:
    print('Collecting', title)
    report.append('\\n===== %s =====\\n$ %s\\n%s' % (title, cmd, run_ssh(cmd, timeout=25)))

out=Path.cwd() / ('router_diagnostics_%s.txt' % datetime.now().strftime('%Y%m%d_%H%M%S'))
out.write_text('\\n'.join(report), encoding='utf-8', errors='replace')
print('REPORT:', out)
'@
$PyCode | Set-Content -LiteralPath $PyFile -Encoding UTF8
Push-Location $Base
& $Python $PyFile
Pop-Location
if ($LASTEXITCODE -ne 0) { throw 'Diagnostics failed.' }
'''

header = r'''@echo off
setlocal
cd /d "%~dp0"
set "SELF=%~f0"
echo Router diagnostics collector
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$m='###__PAYLOAD_START__###'; $s=Get-Content -Raw -LiteralPath $env:SELF; $i=$s.LastIndexOf($m); if($i -lt 0){throw 'payload marker not found'}; $ps=$s.Substring($i+$m.Length); Invoke-Expression $ps"
echo.
pause
exit /b
###__PAYLOAD_START__###
'''

out.write_text(header + payload, encoding="ascii")
print(out)
print(out.stat().st_size)
