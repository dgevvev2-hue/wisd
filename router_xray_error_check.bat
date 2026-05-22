@echo off
setlocal
cd /d "%~dp0"
set "SELF=%~f0"
echo Router Xray error check
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$m='###__PAYLOAD_START__###'; $s=Get-Content -Raw -LiteralPath $env:SELF; $i=$s.LastIndexOf($m); if($i -lt 0){throw 'payload marker not found'}; $ps=$s.Substring($i+$m.Length); Invoke-Expression $ps"
echo.
pause
exit /b
###__PAYLOAD_START__###

$ErrorActionPreference = 'Stop'
$Base = Split-Path -Parent $env:SELF
$Work = Join-Path $env:TEMP ('router-xray-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $Work | Out-Null
function Test-Python { param([string]$Path)
    if (!$Path -or !(Test-Path $Path)) { return $false }
    if ($Path -like '*\WindowsApps\python.exe' -or $Path -like '*\WindowsApps\python3.exe') { return $false }
    try { & $Path -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' 2>$null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}
function Find-Python {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Python $cmd.Source)) { return $cmd.Source }
    $cmd = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Python $cmd.Source)) { return $cmd.Source }
    foreach ($p in @((Join-Path $Base 'python\python.exe'), "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe", 'C:\Python312\python.exe', 'C:\Python311\python.exe', 'C:\Python310\python.exe', 'C:\Program Files\Python312\python.exe', 'C:\Program Files\Python311\python.exe', 'C:\Program Files\Python310\python.exe')) {
        if ($p -and (Test-Python $p)) { return $p }
    }
    throw 'Python not found'
}
$Python = Find-Python
try { & $Python -c "import paramiko, sys; sys.exit(0 if paramiko.__version__ == '3.5.1' else 1)" 2>$null; $ok = ($LASTEXITCODE -eq 0) } catch { $ok = $false }
if (!$ok) { & $Python -m pip install --user --force-reinstall 'paramiko==3.5.1' }
$PyFile = Join-Path $Work 'xray_check.py'
$PyCode = @'
import socket, time
from pathlib import Path
import paramiko
HOST='192.168.0.1'; USER='superadmin'; PASSWORD='8WHoDt3yCQR98BRx'
last=0.0
def prefer(sec,name,wanted):
    if not hasattr(sec,name): return
    cur=list(getattr(sec,name)); out=[x for x in wanted if x in cur]+[x for x in cur if x not in wanted]
    if out: setattr(sec,name,out)
def cli():
    sock=socket.create_connection((HOST,22),timeout=15); t=paramiko.Transport(sock); sec=t.get_security_options()
    prefer(sec,'kex',['diffie-hellman-group1-sha1','diffie-hellman-group14-sha1']); prefer(sec,'key_types',['ssh-rsa']); prefer(sec,'ciphers',['aes128-cbc','3des-cbc','aes256-cbc','aes128-ctr']); prefer(sec,'digests',['hmac-sha1','hmac-sha1-96','hmac-md5'])
    t.start_client(timeout=20); t.auth_password(USER,PASSWORD)
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy()); c._transport=t; return c
def run(cmd, timeout=35):
    global last
    wait=.5-(time.time()-last)
    if wait>0: time.sleep(wait)
    c=cli()
    try:
        _,stdout,_=c.exec_command(cmd+' 2>&1',timeout=timeout); ch=stdout.channel; buf=b''; end=time.time()+timeout
        while time.time()<end:
            if ch.recv_ready(): buf+=ch.recv(4096)
            if ch.exit_status_ready():
                while ch.recv_ready(): buf+=ch.recv(4096)
                break
            time.sleep(.1)
        last=time.time(); return buf.decode('utf-8','replace')
    finally:
        c.close()
cmds=[
('/var/tmp/xray version', '/var/tmp/xray version'),
('current state/status', 'QUERY_STRING=action=status /var/tmp/vpnui/www/cgi-bin/vpn.cgi'),
('active config full', '/var/tmp/vpnui/bin/busybox-mips cat /var/tmp/vpnui/active.json 2>/dev/null'),
('xray log full', '/var/tmp/vpnui/bin/busybox-mips cat /var/tmp/vpnui/xray.log 2>/dev/null'),
('try xray test config', 'XRAY_LOCATION_ASSET=/var/tmp/vpnui /var/tmp/xray test -config /var/tmp/vpnui/active.json 2>&1'),
('try start selected id 2', 'QUERY_STRING=action=connect\\&id=2\\&mode=tunnel /var/tmp/vpnui/www/cgi-bin/vpn.cgi; /var/tmp/vpnui/bin/busybox-mips cat /var/tmp/vpnui/xray.log 2>/dev/null; ps | grep \"[x]ray\"'),
]
report=[]
for title,cmd in cmds:
    print('RUN', title)
    report.append('\\n===== '+title+' =====\\n$ '+cmd+'\\n'+run(cmd, timeout=45))
out=Path.cwd()/('router_xray_error_report.txt')
out.write_text('\\n'.join(report),encoding='utf-8',errors='replace')
print('REPORT:', out)
'@
$PyCode | Set-Content -LiteralPath $PyFile -Encoding UTF8
Push-Location $Base
& $Python $PyFile
Pop-Location
