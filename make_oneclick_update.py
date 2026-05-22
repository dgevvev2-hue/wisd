import base64
from pathlib import Path

root = Path(__file__).resolve().parent
index_b64 = base64.b64encode((root / "vpnui/site/index.html").read_bytes()).decode("ascii")
sub_b64 = base64.b64encode((root / "vpnui/site/cgi-bin/subscription.cgi").read_bytes()).decode("ascii")
sel_b64 = base64.b64encode((root / "vpnui/site/cgi-bin/selective.cgi").read_bytes()).decode("ascii")
info_b64 = base64.b64encode((root / "vpnui/site/cgi-bin/info.cgi").read_bytes()).decode("ascii")
system_b64 = base64.b64encode((root / "vpnui/site/cgi-bin/system.cgi").read_bytes()).decode("ascii")
out = root / "router_upload_update_oneclick.bat"

header = r'''@echo off
setlocal
cd /d "%~dp0"
set "SELF=%~f0"
echo Uploading Router VPN update...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$m='###__PAYLOAD_START__###'; $s=Get-Content -Raw -LiteralPath $env:SELF; $i=$s.LastIndexOf($m); if($i -lt 0){throw 'payload marker not found'}; $ps=$s.Substring($i+$m.Length); Invoke-Expression $ps"
echo.
pause
exit /b
###__PAYLOAD_START__###
'''

payload = r'''
$ErrorActionPreference = 'Stop'
$Base = Split-Path -Parent $env:SELF
$Work = Join-Path $env:TEMP ('router-vpn-update-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $Work | Out-Null
$IndexPath = Join-Path $Work 'index.html'
$SubDir = Join-Path $Work 'cgi-bin'
New-Item -ItemType Directory -Force -Path $SubDir | Out-Null
$SubPath = Join-Path $SubDir 'subscription.cgi'
$SelPath = Join-Path $SubDir 'selective.cgi'
$InfoPath = Join-Path $SubDir 'info.cgi'
$SystemPath = Join-Path $SubDir 'system.cgi'
[IO.File]::WriteAllBytes($IndexPath, [Convert]::FromBase64String('__INDEX_B64__'))
[IO.File]::WriteAllBytes($SubPath, [Convert]::FromBase64String('__SUB_B64__'))
[IO.File]::WriteAllBytes($SelPath, [Convert]::FromBase64String('__SEL_B64__'))
[IO.File]::WriteAllBytes($InfoPath, [Convert]::FromBase64String('__INFO_B64__'))
[IO.File]::WriteAllBytes($SystemPath, [Convert]::FromBase64String('__SYSTEM_B64__'))

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
$PyFile = Join-Path $Work 'upload_update.py'
$PyCode = @'
import os, time, socket
from pathlib import Path
import paramiko
HOST='192.168.0.1'; USER='superadmin'; PASSWORD='8WHoDt3yCQR98BRx'
USB_ROOT='/var/usbmnt/sda1/vpnui/www'; RAM_ROOT='/var/tmp/vpnui/www'; BB='/var/tmp/vpnui/bin/busybox-mips'
LOCAL=Path(os.environ['ROUTER_UPDATE_WORK'])
MIN_GAP=0.45; last_run=0.0

def shell_q(s): return "'" + s.replace("'", "'\\''") + "'"
def hex_escape(b): return ''.join('\\x%02x' % x for x in b)
def prefer(sec, name, wanted):
    if not hasattr(sec, name): return
    cur=list(getattr(sec,name)); out=[x for x in wanted if x in cur]+[x for x in cur if x not in wanted]
    if out: setattr(sec,name,out)
def open_client():
    sock=socket.create_connection((HOST,22),timeout=15)
    t=paramiko.Transport(sock)
    sec=t.get_security_options()
    prefer(sec,'kex',['diffie-hellman-group1-sha1','diffie-hellman-group14-sha1'])
    prefer(sec,'key_types',['ssh-rsa'])
    prefer(sec,'ciphers',['aes128-cbc','3des-cbc','aes256-cbc','aes128-ctr'])
    prefer(sec,'digests',['hmac-sha1','hmac-sha1-96','hmac-md5'])
    t.start_client(timeout=20); t.auth_password(USER,PASSWORD)
    if not t.is_authenticated(): raise RuntimeError('SSH password auth failed')
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy()); c._transport=t
    return c

def run_ssh(cmd, timeout=35, tries=6):
    global last_run
    err=None
    for attempt in range(tries):
        wait=MIN_GAP + attempt*0.8 - (time.time()-last_run)
        if wait>0: time.sleep(wait)
        c=None
        try:
            c=open_client()
            _,stdout,_=c.exec_command(cmd+' 2>&1',timeout=timeout)
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
            err=e; last_run=time.time(); time.sleep(1.5)
        finally:
            try:
                if c: c.close()
            except Exception: pass
    raise err

def ok(out):
    if '__OK__' not in out: raise RuntimeError(out[-700:])

def push(rel, src):
    data=Path(src).read_bytes(); make_exec=rel.endswith('.cgi') or rel.endswith('.sh')
    print('PUT %s (%d bytes)' % (rel, len(data)))
    dst='%s/%s' % (USB_ROOT, rel); tmp=dst+'.tmp'; d=os.path.dirname(dst)
    ok(run_ssh('mkdir -p %s; echo __OK__' % shell_q(d)))
    chunk=200; total=max(1,(len(data)+chunk-1)//chunk)
    for i in range(total):
        part=data[i*chunk:(i+1)*chunk]
        redir='>' if i==0 else '>>'
        ok(run_ssh("%s printf '%%b' '%s' %s %s; echo __OK__" % (BB, hex_escape(part), redir, shell_q(tmp)), timeout=30))
        if (i+1)%16==0 or i+1==total: print('  chunk %d/%d' % (i+1,total))
    ok(run_ssh('mv %s %s; echo __OK__' % (shell_q(tmp), shell_q(dst))))
    ram='%s/%s' % (RAM_ROOT, rel); rd=os.path.dirname(ram)
    cmd='mkdir -p %s; cp -a %s %s; ' % (shell_q(rd), shell_q(dst), shell_q(ram))
    if make_exec: cmd += 'chmod +x %s; ' % shell_q(ram)
    ok(run_ssh(cmd+'echo __OK__'))

print('Preparing router...')
ok(run_ssh("mkdir -p /var/usbmnt/sda1 /var/tmp/vpnui/bin /var/tmp/vpnui/www; mount | grep '/var/usbmnt/sda1' >/dev/null || mount -t ext2 /dev/sda1 /var/usbmnt/sda1; cp /var/usbmnt/sda1/vpnui/bin/busybox-mips /var/tmp/vpnui/bin/busybox-mips; chmod +x /var/tmp/vpnui/bin/busybox-mips; echo __OK__", timeout=40))
push('cgi-bin/subscription.cgi', LOCAL/'cgi-bin'/'subscription.cgi')
push('cgi-bin/selective.cgi', LOCAL/'cgi-bin'/'selective.cgi')
push('cgi-bin/info.cgi', LOCAL/'cgi-bin'/'info.cgi')
push('cgi-bin/system.cgi', LOCAL/'cgi-bin'/'system.cgi')
push('index.html', LOCAL/'index.html')
print('Starting panel port 8083...')
run_ssh("ps | grep '/var/tmp/vpnui/bin/busybox-mips httpd' | grep -v grep | awk '{print $1}' | xargs kill -9 2>/dev/null || true; /var/tmp/vpnui/bin/busybox-mips httpd -f -p 192.168.0.1:8083 -h /var/tmp/vpnui/www >/var/tmp/vpnui/httpd.log 2>&1 & iptables -C INPUT -i br2 -p tcp --dport 8083 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -i br2 -p tcp --dport 8083 -j ACCEPT; echo __OK__", timeout=25)
print('Done. Open: http://192.168.0.1:8083/')
'@
$PyCode | Set-Content -LiteralPath $PyFile -Encoding UTF8
$env:ROUTER_UPDATE_WORK = $Work
Write-Host 'Uploading updated files to router...'
& $Python $PyFile
if ($LASTEXITCODE -ne 0) { throw 'Upload failed.' }
Write-Host ''
Write-Host 'Done. Open: http://192.168.0.1:8083/'
'''

payload = payload.replace("__INDEX_B64__", index_b64).replace("__SUB_B64__", sub_b64).replace("__SEL_B64__", sel_b64).replace("__INFO_B64__", info_b64).replace("__SYSTEM_B64__", system_b64)
out.write_text(header + payload, encoding="ascii")
print(out)
print(out.stat().st_size)
