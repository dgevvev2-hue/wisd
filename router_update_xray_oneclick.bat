@echo off
setlocal
cd /d "%~dp0"
set "SELF=%~f0"
echo Router Xray updater
echo This updates Xray only. It will NOT start VPN automatically.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$m='###__PAYLOAD_START__###'; $s=Get-Content -Raw -LiteralPath $env:SELF; $i=$s.LastIndexOf($m); if($i -lt 0){throw 'payload marker not found'}; $ps=$s.Substring($i+$m.Length); Invoke-Expression $ps"
echo.
pause
exit /b
###__PAYLOAD_START__###

$ErrorActionPreference = 'Stop'
$Base = Split-Path -Parent $env:SELF
$Work = Join-Path $env:TEMP ('router-xray-update-' + [guid]::NewGuid().ToString('N'))
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

$PyFile = Join-Path $Work 'update_xray.py'
$PyCode = @'
import http.server, os, shutil, socket, socketserver, sys, tempfile, threading, time, urllib.request, zipfile
from pathlib import Path
import paramiko

HOST='192.168.0.1'
USER='superadmin'
PASSWORD='8WHoDt3yCQR98BRx'
USB_XRAY='/var/usbmnt/sda1/vpnui/xray'
RAM_XRAY='/var/tmp/xray'
BB='/var/tmp/vpnui/bin/busybox-mips'
URLS=[
    # XHTTP with stream-one was added in v24.11.30. Newer official MIPS
    # builds can crash on this router's old 3.18 MIPS kernel, so try older
    # compatible releases before giving up.
    ('v25.3.6-mips32', 'https://github.com/XTLS/Xray-core/releases/download/v25.3.6/Xray-linux-mips32.zip'),
    ('v25.1.30-mips32', 'https://github.com/XTLS/Xray-core/releases/download/v25.1.30/Xray-linux-mips32.zip'),
    ('v24.12.18-mips32', 'https://github.com/XTLS/Xray-core/releases/download/v24.12.18/Xray-linux-mips32.zip'),
    ('v24.11.30-mips32', 'https://github.com/XTLS/Xray-core/releases/download/v24.11.30/Xray-linux-mips32.zip'),
    ('v25.3.6-mips32le', 'https://github.com/XTLS/Xray-core/releases/download/v25.3.6/Xray-linux-mips32le.zip'),
    ('v24.11.30-mips32le', 'https://github.com/XTLS/Xray-core/releases/download/v24.11.30/Xray-linux-mips32le.zip'),
]
BASE=Path(os.environ.get('ROUTER_XRAY_BASE', os.getcwd()))
WORK=Path(os.environ['ROUTER_XRAY_WORK'])
last_run=0.0

def prefer(sec, name, wanted):
    if not hasattr(sec, name):
        return
    cur=list(getattr(sec, name))
    out=[x for x in wanted if x in cur]+[x for x in cur if x not in wanted]
    if out:
        setattr(sec, name, out)

def open_client():
    sock=socket.create_connection((HOST,22),timeout=15)
    t=paramiko.Transport(sock)
    sec=t.get_security_options()
    prefer(sec,'kex',['diffie-hellman-group1-sha1','diffie-hellman-group14-sha1'])
    prefer(sec,'key_types',['ssh-rsa'])
    prefer(sec,'ciphers',['aes128-cbc','3des-cbc','aes256-cbc','aes128-ctr'])
    prefer(sec,'digests',['hmac-sha1','hmac-sha1-96','hmac-md5'])
    t.start_client(timeout=20)
    t.auth_password(USER,PASSWORD)
    if not t.is_authenticated():
        raise RuntimeError('SSH password auth failed')
    c=paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c._transport=t
    return c

def run_ssh(cmd, timeout=60, tries=3):
    global last_run
    err=None
    for attempt in range(tries):
        wait=0.45 + attempt*0.8 - (time.time()-last_run)
        if wait>0:
            time.sleep(wait)
        c=None
        try:
            c=open_client()
            _,stdout,_=c.exec_command(cmd+' 2>&1',timeout=timeout)
            ch=stdout.channel
            ch.settimeout(0.4)
            buf=b''
            end=time.time()+timeout
            while time.time()<end:
                try:
                    if ch.recv_ready():
                        buf += ch.recv(8192)
                except socket.timeout:
                    pass
                if ch.exit_status_ready():
                    while ch.recv_ready():
                        buf += ch.recv(8192)
                    break
                time.sleep(0.1)
            try:
                code=ch.recv_exit_status() if ch.exit_status_ready() else 124
            except Exception:
                code=125
            try:
                ch.close()
            except Exception:
                pass
            last_run=time.time()
            return code, buf.decode('utf-8','replace')
        except Exception as e:
            err=e
            last_run=time.time()
            time.sleep(1.0)
        finally:
            try:
                if c:
                    c.close()
            except Exception:
                pass
    raise RuntimeError('SSH failed: %r' % (err,))

def local_ip_to_router():
    s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((HOST, 80))
        return s.getsockname()[0]
    finally:
        s.close()

def download(url, dest):
    req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest,'wb') as f:
        total=int(r.headers.get('Content-Length') or 0)
        got=0
        last_pct=-10
        while True:
            chunk=r.read(1024*512)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total:
                pct=int(got*100/total)
                if pct >= last_pct + 10 or pct >= 100:
                    print('  download %d%%' % pct)
                    last_pct=pct
    return dest

def extract_xray(zip_path, target_dir):
    with zipfile.ZipFile(zip_path) as z:
        names=z.namelist()
        member=None
        for n in names:
            if n.rstrip('/').endswith('/xray') or n == 'xray':
                member=n
                break
        if not member:
            raise RuntimeError('xray binary not found in %s' % zip_path)
        z.extract(member, target_dir)
        src=target_dir / member
        out=target_dir / 'xray'
        if src != out:
            shutil.copyfile(src, out)
        return out

class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

def serve_dir(path):
    class ReuseTCPServer(socketserver.TCPServer):
        allow_reuse_address=True
    os.chdir(path)
    srv=ReuseTCPServer(('0.0.0.0',0), QuietHandler)
    port=srv.server_address[1]
    th=threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, port

def router_fetch_and_test(local_ip, port):
    url='http://%s:%s/xray' % (local_ip, port)
    cmd = r'''
set -e
mkdir -p /var/tmp/vpnui /var/usbmnt/sda1/vpnui
rm -f /var/tmp/xray.new /var/tmp/xray.new.version
({bb} wget -O /var/tmp/xray.new {url} || wget -O /var/tmp/xray.new {url})
chmod +x /var/tmp/xray.new
/var/tmp/xray.new version >/var/tmp/xray.new.version 2>&1
cat /var/tmp/xray.new.version
'''.format(bb=BB, url=url)
    return run_ssh(cmd, timeout=180, tries=2)

def install_tested():
    cmd = r'''
set -e
TS=$(cat /proc/uptime 2>/dev/null | awk '{print int($1)}')
[ -n "$TS" ] || TS=now
mkdir -p /var/usbmnt/sda1/vpnui /var/tmp/vpnui
if [ -x /var/tmp/xray ]; then cp /var/tmp/xray /var/tmp/vpnui/xray.bak.$TS 2>/dev/null || true; fi
if [ -x /var/usbmnt/sda1/vpnui/xray ]; then cp /var/usbmnt/sda1/vpnui/xray /var/usbmnt/sda1/vpnui/xray.bak.$TS 2>/dev/null || true; fi
PID=$(ps | grep '[x]ray' | awk '{print $1}' | head -1)
[ -n "$PID" ] && kill -9 "$PID" 2>/dev/null || true
cp /var/tmp/xray.new /var/tmp/xray
cp /var/tmp/xray.new /var/usbmnt/sda1/vpnui/xray
chmod +x /var/tmp/xray /var/usbmnt/sda1/vpnui/xray
/var/tmp/xray version
echo INSTALLED_OK
'''.strip()
    return run_ssh(cmd, timeout=90, tries=2)

def main():
    print('Checking router current Xray...')
    code,out=run_ssh('/var/tmp/xray version 2>&1 || true', timeout=20)
    print(out.strip())
    ip=local_ip_to_router()
    print('PC LAN IP:', ip)
    print('If Windows Firewall asks about Python, allow Private networks.')

    last_error=None
    for arch,url in URLS:
        try:
            print('Trying official Xray asset:', arch)
            zpath=WORK / ('xray-%s.zip' % arch)
            download(url, zpath)
            d=WORK / ('extract-' + arch)
            d.mkdir(parents=True, exist_ok=True)
            xray=extract_xray(zpath, d)
            serve_root=WORK / ('serve-' + arch)
            serve_root.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(xray, serve_root / 'xray')
            srv,port=serve_dir(serve_root)
            try:
                code,out=router_fetch_and_test(ip, port)
            finally:
                srv.shutdown()
                srv.server_close()
            print(out.strip())
            bad_runtime = ('SIGSEGV' in out or 'futexwakeup' in out or 'applet not found' in out)
            if code != 0 or 'Xray ' not in out or bad_runtime:
                last_error='router test failed for %s: %s' % (arch, out[-800:])
                print(last_error)
                continue
            print('Installing tested Xray...')
            code,out=install_tested()
            print(out.strip())
            if code != 0 or 'INSTALLED_OK' not in out:
                raise RuntimeError('install failed: ' + out[-1000:])
            print('')
            print('DONE. Xray updated. VPN tunnel was NOT started.')
            print('Now open panel and start the selected xhttp server again.')
            return
        except Exception as e:
            last_error=repr(e)
            print('FAILED %s: %s' % (arch, last_error))
    raise RuntimeError('No official Xray binary worked on this router. The router likely needs a custom MIPS build with old-kernel Go runtime patches, or a non-XHTTP subscription. Last error: %s' % last_error)

if __name__ == '__main__':
    main()
'@
$PyCode | Set-Content -LiteralPath $PyFile -Encoding UTF8
$env:ROUTER_XRAY_WORK = $Work
$env:ROUTER_XRAY_BASE = $Base
Push-Location $Base
& $Python $PyFile
Pop-Location
if ($LASTEXITCODE -ne 0) { throw 'Xray update failed.' }
