from pathlib import Path

root = Path(__file__).resolve().parent
out = root / "router_import_subscription_oneclick.bat"

import base64, json
backup = {
    "nodes.json": base64.b64encode((root / "vpnui/site/nodes.json").read_bytes()).decode("ascii"),
    "nodes.txt": base64.b64encode((root / "vpnui/site/nodes.txt").read_bytes()).decode("ascii"),
    "configs": {x.name: base64.b64encode(x.read_bytes()).decode("ascii") for x in sorted((root / "vpnui/site/configs").glob("*.json"))},
}
backup_json = json.dumps(backup, separators=(",", ":"))

payload = r'''
$ErrorActionPreference = 'Stop'
$Base = Split-Path -Parent $env:SELF
$SubUrl = Read-Host 'Paste VPN subscription URL'
if (!$SubUrl.Trim()) { throw 'Empty URL' }
$Work = Join-Path $env:TEMP ('router-vpn-sub-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $Work | Out-Null
$BackupJsonPath = Join-Path $Work 'backup.json'
@'
__BACKUP_JSON__
'@ | Set-Content -LiteralPath $BackupJsonPath -Encoding ASCII

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
$YamlOk = $false
try { & $Python -c "import yaml" 2>$null; $YamlOk = ($LASTEXITCODE -eq 0) } catch { $YamlOk = $false }
if (!$YamlOk) {
    Write-Host 'Installing YAML parser...'
    & $Python -m pip install --user PyYAML
    if ($LASTEXITCODE -ne 0) { throw 'PyYAML install failed. Check internet connection.' }
}

$PyFile = Join-Path $Work 'import_subscription.py'
$PyCode = @'
import base64, json, os, re, socket, sys, time, urllib.parse, urllib.request
from pathlib import Path
import paramiko
import yaml

HOST='192.168.0.1'; USER='superadmin'; PASSWORD='8WHoDt3yCQR98BRx'
USB_ROOT='/var/usbmnt/sda1/vpnui/www'; RAM_ROOT='/var/tmp/vpnui/www'; BB='/var/tmp/vpnui/bin/busybox-mips'
WORK=Path(os.environ['ROUTER_SUB_WORK'])
URL=os.environ['ROUTER_SUB_URL'].strip()
HWID=os.environ.get('ROUTER_SUB_HWID','router-vpn-5200293391')
MIN_GAP=0.45; last_run=0.0

def sub_meta():
    u=unwrap_url(URL)
    host=urllib.parse.urlparse(u).hostname or 'subscription'
    sid='sub_' + re.sub(r'[^A-Za-z0-9._-]+','_',host)[:40]
    name='ProtectedLine' if 'protectedline' in host.lower() else host
    return sid, name, u

def unwrap_url(u):
    if u.startswith('flclashx://') or u.startswith('clash://'):
        q=urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
        if q.get('url'): return q['url'][0]
    return u

def download(u):
    u=unwrap_url(u)
    uas=[
        'v2RayTun/6.0',
        'Happ/1.0.0',
        'FlClashX/0.8.83',
        'ClashforWindows/0.20.39',
        'Clash.Meta',
        'mihomo/1.18',
        'FLClash/1.0',
        'Shadowrocket/2.2.0',
        'sing-box/1.9.0',
        'Mozilla/5.0',
    ]
    errors=[]
    for ua in uas:
        try:
            headers={
                'User-Agent':ua,
                'Accept':'*/*',
                'x-hwid':HWID,
                'x-device-os':'Router',
                'x-device-model':'RT-GM2-9',
                'x-ver-os':'3.18.21',
            }
            req=urllib.request.Request(u,headers=headers)
            with urllib.request.urlopen(req,timeout=25) as r:
                data=r.read()
            text=data.decode('utf-8','replace')
            decoded=try_base64(text) or text
            bad=('App not supported' in decoded) or re.search(r'proxies:\s*\[\]', decoded) or ('0.0.0.0:1' in decoded)
            print(f'DOWNLOAD ua={ua} bytes={len(data)} bad={bool(bad)}')
            if data and not bad:
                return text
            errors.append(f'{ua}: empty/unsupported')
        except Exception as e:
            errors.append(f'{ua}: {e}')
    raise RuntimeError('No usable subscription. Last errors: ' + ' | '.join(errors[-3:]))

def try_base64(s):
    clean=''.join(s.split())
    if not clean or len(clean)<8: return ''
    pad='='*((4-len(clean)%4)%4)
    try:
        return base64.b64decode(clean+pad).decode('utf-8','replace')
    except Exception:
        return ''

def parse_qs(q):
    return {k:v[0] for k,v in urllib.parse.parse_qs(q,keep_blank_values=True).items()}

def node_from_vless(link, i):
    p=urllib.parse.urlparse(link)
    uuid=p.username or ''
    host=p.hostname or ''
    port=p.port or 443
    q=parse_qs(p.query)
    name=urllib.parse.unquote(p.fragment or f'node-{i}')
    if not uuid or not host: return None
    if name.lower().strip() == 'app not supported': return None
    if host in ('0.0.0.0','127.0.0.1') or int(port) <= 1: return None
    if uuid == '00000000-0000-0000-0000-000000000000': return None
    return {
        'id': i, 'name': name, 'uuid': uuid, 'host': host, 'port': port,
        'network': q.get('type','tcp') or 'tcp',
        'security': q.get('security','none') or 'none',
        'sni': q.get('sni') or q.get('serverName') or q.get('servername') or host,
        'fp': q.get('fp') or q.get('fingerprint') or 'chrome',
        'pbk': q.get('pbk') or q.get('publicKey') or '',
        'sid': q.get('sid') or q.get('shortId') or '',
        'spx': q.get('spx') or '/',
        'flow': q.get('flow') or '',
        'service': q.get('serviceName') or q.get('grpc-service-name') or '',
        'path': q.get('path') or '/',
        'mode': q.get('mode') or 'auto',
        'host_header': q.get('host') or q.get('authority') or '',
        'extra': q.get('extra') or '',
        'concurrency': q.get('concurrency') or '',
    }

def stripq(v):
    v=v.strip().strip('"').strip("'")
    return v

def parse_scalar(v):
    v=stripq(v)
    if v.lower() in ('true','false'): return v.lower()=='true'
    try: return int(v)
    except Exception: return v

def parse_clash(text):
    try:
        data=yaml.safe_load(text) or {}
        proxies=data.get('proxies') or []
        out=[]
        for n in proxies:
            if not isinstance(n, dict): continue
            if str(n.get('type','')).lower()!='vless': continue
            host=str(n.get('server','') or '')
            uuid=str(n.get('uuid','') or n.get('password','') or '')
            port=int(n.get('port') or 443)
            name=str(n.get('name') or f'node-{len(out)}')
            if not host or not uuid or port <= 1: continue
            if name.lower().strip() == 'app not supported': continue
            if host in ('0.0.0.0','127.0.0.1'): continue
            if uuid == '00000000-0000-0000-0000-000000000000': continue
            reality=n.get('reality-opts') or {}
            xhttp=n.get('xhttp-opts') or {}
            if not isinstance(xhttp, dict): xhttp={}
            tls=bool(n.get('tls'))
            net=str(n.get('network') or 'tcp')
            out.append({
                'id': len(out), 'name': name,
                'uuid': uuid, 'host': host, 'port': port,
                'network': net,
                'security': 'reality' if reality else ('tls' if tls else 'none'),
                'sni': str(n.get('servername') or n.get('sni') or reality.get('server-name') or reality.get('servername') or host),
                'fp': str(n.get('client-fingerprint') or n.get('fingerprint') or 'chrome'),
                'pbk': str(reality.get('public-key') or n.get('public-key') or ''),
                'sid': str(reality.get('short-id') or n.get('short-id') or ''),
                'spx': str(reality.get('spider-x') or n.get('spider-x') or '/'),
                'flow': str(n.get('flow') or ''),
                'service': str(n.get('grpc-opts',{}).get('grpc-service-name') if isinstance(n.get('grpc-opts'),dict) else n.get('grpc-service-name') or n.get('service-name') or ''),
                'path': str(xhttp.get('path') or n.get('path') or '/'),
                'mode': str(xhttp.get('mode') or n.get('mode') or 'auto'),
                'host_header': str(xhttp.get('host') or n.get('host') or ''),
                'extra': str(xhttp.get('extra') or n.get('extra') or ''),
                'concurrency': str(xhttp.get('concurrency') or n.get('concurrency') or ''),
            })
        if out:
            return out
    except Exception as e:
        print('YAML parser fallback:', e)

    nodes=[]
    in_proxies=False
    cur=None
    for raw in text.splitlines():
        line=raw.rstrip()
        if not line.strip() or line.lstrip().startswith('#'): continue
        if re.match(r'^proxies:\s*$', line):
            in_proxies=True; continue
        if in_proxies and re.match(r'^[A-Za-z0-9_-]+:', line) and not line.startswith(' '):
            break
        if not in_proxies: continue
        m=re.match(r'^\s*-\s+name:\s*(.+)$', line)
        if m:
            if cur: nodes.append(cur)
            cur={'name':stripq(m.group(1))}
            continue
        if cur is None: continue
        m=re.match(r'^\s+([A-Za-z0-9_.-]+):\s*(.*)$', line)
        if m:
            cur[m.group(1)]=parse_scalar(m.group(2))
    if cur: nodes.append(cur)
    out=[]
    for n in nodes:
        if str(n.get('type','')).lower()!='vless': continue
        host=str(n.get('server','') or '')
        uuid=str(n.get('uuid','') or n.get('password','') or '')
        port=int(n.get('port') or 443)
        if not host or not uuid or port <= 1: continue
        if str(n.get('name','')).lower().strip() == 'app not supported': continue
        if host in ('0.0.0.0','127.0.0.1'): continue
        if uuid == '00000000-0000-0000-0000-000000000000': continue
        out.append({
            'id': len(out), 'name': str(n.get('name') or f'node-{len(out)}'),
            'uuid': uuid, 'host': host, 'port': port,
            'network': str(n.get('network') or 'tcp'),
            'security': 'reality' if n.get('reality-opts') or n.get('public-key') else ('tls' if n.get('tls') else 'none'),
            'sni': str(n.get('servername') or n.get('sni') or host),
            'fp': str(n.get('client-fingerprint') or n.get('fingerprint') or 'chrome'),
            'pbk': str(n.get('public-key') or ''),
            'sid': str(n.get('short-id') or ''),
            'spx': '/',
            'flow': str(n.get('flow') or ''),
            'service': str(n.get('grpc-service-name') or n.get('service-name') or ''),
        })
    return out

def parse_nodes(text):
    candidates=[text]
    b=try_base64(text)
    if b: candidates.append(b)
    for s in candidates:
        links=re.findall(r'vless://[^\s]+', s)
        nodes=[]
        for link in links:
            n=node_from_vless(link, len(nodes))
            if n: nodes.append(n)
        if nodes: return nodes
        nodes=parse_clash(s)
        if nodes: return nodes
    raise RuntimeError('Subscription parsed, but no supported VLESS nodes found')

def xray_config(n):
    user={'id':n['uuid'],'encryption':'none'}
    if n.get('flow'): user['flow']=n['flow']
    stream={'network':n['network'],'security':n['security']}
    if n['security']=='reality':
        stream['realitySettings']={'serverName':n.get('sni') or n['host'],'fingerprint':n.get('fp') or 'chrome','publicKey':n.get('pbk') or '','shortId':n.get('sid') or '','spiderX':n.get('spx') or '/'}
    elif n['security']=='tls':
        stream['tlsSettings']={'serverName':n.get('sni') or n['host'],'fingerprint':n.get('fp') or 'chrome'}
    if n['network']=='grpc':
        stream['grpcSettings']={'serviceName':n.get('service') or ''}
    if n['network'] in ('xhttp','splithttp'):
        xs={'path': n.get('path') or '/'}
        if n.get('mode') and n.get('mode') != 'auto':
            xs['mode']=n.get('mode')
        if n.get('host_header'):
            xs['host']=n.get('host_header')
        if n.get('extra'):
            xs['extra']=n.get('extra')
        if n.get('concurrency'):
            try:
                c=int(n.get('concurrency'))
                xs['scMaxConcurrentPosts']={'from':c,'to':c}
            except Exception:
                pass
        stream['xhttpSettings']=xs
    return {
        'log': {'loglevel':'info','access':'/var/tmp/vpnui/xray.access.log'},
        'inbounds': [
            {'tag':'socks-in','listen':'192.168.0.1','port':1080,'protocol':'socks','settings':{'auth':'noauth','udp':False}},
            {'tag':'http-in','listen':'192.168.0.1','port':1081,'protocol':'http','settings':{}},
            {'tag':'redir-in','listen':'0.0.0.0','port':12345,'protocol':'dokodemo-door','settings':{'network':'tcp','followRedirect':True},'sniffing':{'enabled':True,'destOverride':['http','tls']}},
        ],
        'outbounds': [
            {'tag':'vpn-out','protocol':'vless','settings':{'vnext':[{'address':n['host'],'port':int(n['port']),'users':[user]}]},'streamSettings':stream},
            {'tag':'direct','protocol':'freedom'},
        ],
        'routing': {'domainStrategy':'IPIfNonMatch','rules':[]},
    }

def write_local(nodes):
    cfg=WORK/'configs'; cfg.mkdir(exist_ok=True)
    nodes_json=[]
    with (WORK/'nodes.txt').open('w',encoding='utf-8') as f:
        for n in nodes:
            ip=n['host'] if re.match(r'^\d+\.\d+\.\d+\.\d+$', n['host']) else ''
            f.write(f"{n['id']}|node-{n['id']}|{n['host']}||{ip}\n")
            nodes_json.append({'id':n['id'],'name':n['name'],'host':n['host'],'port':int(n['port']),'ips':[ip] if ip else [],'ping':None,'network':n['network']})
            (cfg/f"{n['id']}.json").write_text(json.dumps(xray_config(n),ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (WORK/'nodes.json').write_text(json.dumps(nodes_json,ensure_ascii=False,indent=2),encoding='utf-8')

def shell_q(s): return "'" + s.replace("'", "'\\''") + "'"
def hex_escape(b): return ''.join('\\x%02x' % x for x in b)
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
def run_ssh(cmd, timeout=35, tries=6):
    global last_run
    err=None
    for attempt in range(tries):
        wait=MIN_GAP + attempt*0.8 - (time.time()-last_run)
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
            last_run=time.time(); return buf.decode('utf-8','replace')
        except Exception as e:
            err=e; last_run=time.time(); time.sleep(1.5)
        finally:
            try:
                if c: c.close()
            except Exception: pass
    raise err
def ok(out):
    if '__OK__' not in out: raise RuntimeError(out[-700:])
def upload(rel, path):
    data=Path(path).read_bytes(); dst=f'{USB_ROOT}/{rel}'; tmp=dst+'.tmp'; d=os.path.dirname(dst)
    ok(run_ssh(f'mkdir -p {shell_q(d)}; echo __OK__'))
    chunk=200; total=max(1,(len(data)+chunk-1)//chunk)
    print(f'UPLOAD {rel} ({len(data)} bytes)')
    for i in range(total):
        part=data[i*chunk:(i+1)*chunk]; redir='>' if i==0 else '>>'
        ok(run_ssh(f"{BB} printf '%b' '{hex_escape(part)}' {redir} {shell_q(tmp)}; echo __OK__", timeout=30))
        if (i+1)%16==0 or i+1==total: print(f'  chunk {i+1}/{total}')
    ok(run_ssh(f'mv {shell_q(tmp)} {shell_q(dst)}; echo __OK__'))
    ram=f'{RAM_ROOT}/{rel}'; rd=os.path.dirname(ram)
    cmd=f'mkdir -p {shell_q(rd)}; cp -a {shell_q(dst)} {shell_q(ram)}; '
    if rel.endswith('.cgi') or rel.endswith('.sh'): cmd += f'chmod +x {shell_q(ram)}; '
    ok(run_ssh(cmd+'echo __OK__'))
def upload_all(nodes):
    ok(run_ssh("mkdir -p /var/usbmnt/sda1 /var/tmp/vpnui/bin /var/tmp/vpnui/www; mount | grep '/var/usbmnt/sda1' >/dev/null || mount -t ext2 /dev/sda1 /var/usbmnt/sda1; cp /var/usbmnt/sda1/vpnui/bin/busybox-mips /var/tmp/vpnui/bin/busybox-mips; chmod +x /var/tmp/vpnui/bin/busybox-mips; mkdir -p /var/tmp/vpnui/www/configs /var/usbmnt/sda1/vpnui/www/configs; rm -f /var/tmp/vpnui/www/configs/*.json /var/usbmnt/sda1/vpnui/www/configs/*.json; echo __OK__", timeout=45))
    ok(run_ssh(f"mkdir -p /var/LxC; printf '%s\n' {shell_q(unwrap_url(URL))} > /var/LxC/subscription.url; echo __OK__"))
    sid,sname,surl=sub_meta()
    meta=f"mkdir -p /var/LxC; touch /var/LxC/subscriptions.txt; grep -Fv {shell_q(sid+'|')} /var/LxC/subscriptions.txt > /var/LxC/subscriptions.txt.tmp 2>/dev/null; printf '%s|%s|%s|%s|%s\\n' {shell_q(sid)} {shell_q(sname)} {shell_q(surl)} {len(nodes)} 0 >> /var/LxC/subscriptions.txt.tmp; mv /var/LxC/subscriptions.txt.tmp /var/LxC/subscriptions.txt; printf '%s\\n' {shell_q(sid)} > /var/LxC/subscription.active; echo __OK__"
    ok(run_ssh(meta, timeout=25))
    upload('nodes.json', WORK/'nodes.json')
    upload('nodes.txt', WORK/'nodes.txt')
    for n in nodes: upload(f'configs/{n["id"]}.json', WORK/'configs'/f'{n["id"]}.json')

def restore_backup():
    print('Subscription has no usable servers. Restoring built-in backup list...')
    data=json.loads(Path(os.environ['ROUTER_BACKUP_JSON']).read_text(encoding='ascii'))
    (WORK/'configs').mkdir(exist_ok=True)
    (WORK/'nodes.json').write_bytes(base64.b64decode(data['nodes.json']))
    (WORK/'nodes.txt').write_bytes(base64.b64decode(data['nodes.txt']))
    ids=[]
    for name,b64 in data['configs'].items():
        (WORK/'configs'/name).write_bytes(base64.b64decode(b64))
        try: ids.append({'id': int(name.split('.')[0])})
        except Exception: pass
    upload_all(ids)
    print('Backup restored. Bad App not supported node removed.')

try:
    text=download(URL)
    nodes=parse_nodes(text)
    nodes=[n for n in nodes if n.get('name','').lower().strip()!='app not supported' and n.get('host') not in ('0.0.0.0','127.0.0.1') and int(n.get('port') or 0)>1 and n.get('uuid')!='00000000-0000-0000-0000-000000000000']
    if not nodes:
        raise RuntimeError('no usable nodes after filtering')
    for i,n in enumerate(nodes): n['id']=i
    print(f'FOUND {len(nodes)} usable server(s)')
    write_local(nodes)
    upload_all(nodes)
except Exception as e:
    print('IMPORT WARNING:', e)
    restore_backup()
print('Done. Refresh site: http://192.168.0.1:8083/')
'@
$PyCode | Set-Content -LiteralPath $PyFile -Encoding UTF8
$env:ROUTER_SUB_WORK = $Work
$env:ROUTER_SUB_URL = $SubUrl
$env:ROUTER_BACKUP_JSON = $BackupJsonPath
& $Python $PyFile
if ($LASTEXITCODE -ne 0) { throw 'Import failed.' }
'''

header = r'''@echo off
setlocal
cd /d "%~dp0"
set "SELF=%~f0"
echo Router VPN subscription import
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$m='###__PAYLOAD_START__###'; $s=Get-Content -Raw -LiteralPath $env:SELF; $i=$s.LastIndexOf($m); if($i -lt 0){throw 'payload marker not found'}; $ps=$s.Substring($i+$m.Length); Invoke-Expression $ps"
echo.
pause
exit /b
###__PAYLOAD_START__###
'''

payload = payload.replace("__BACKUP_JSON__", backup_json)
out.write_text(header + payload, encoding="ascii")
print(out)
print(out.stat().st_size)
