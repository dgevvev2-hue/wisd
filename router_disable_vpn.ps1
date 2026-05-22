$ErrorActionPreference = "Stop"

$Router = "192.168.0.1"
$User = "superadmin"
$Password = "8WHoDt3yCQR98BRx"

$py = @"
import paramiko, time
host="$Router"; user="$User"; pw="$Password"
def run_ssh(cmd, timeout=30, tries=4):
    last=None
    for i in range(tries):
        try:
            c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(host,22,username=user,password=pw,timeout=15,banner_timeout=15,auth_timeout=15,look_for_keys=False,allow_agent=False,disabled_algorithms={'pubkeys':['rsa-sha2-256','rsa-sha2-512']})
            stdin,stdout,stderr=c.exec_command(cmd + " 2>&1",timeout=timeout)
            ch=stdout.channel
            out=b""
            end=time.time()+timeout
            while time.time()<end:
                if ch.recv_ready():
                    out += ch.recv(4096)
                if ch.exit_status_ready():
                    while ch.recv_ready():
                        out += ch.recv(4096)
                    break
                time.sleep(0.1)
            try:
                ch.close()
            except Exception:
                pass
            out=out.decode("utf-8","replace")
            err=""
            c.close()
            return out,err
        except Exception as e:
            last=e
            try: c.close()
            except Exception: pass
            time.sleep(1.5)
    raise last
cmd=r'''
QUERY_STRING=action=disconnect /var/tmp/vpnui/www/cgi-bin/vpn.cgi >/dev/null 2>&1 || killall xray 2>/dev/null || true
iptables -t nat -D PREROUTING -i br2 -s 192.168.0.0/24 -p tcp -j XRAY 2>/dev/null || true
iptables -t nat -D PREROUTING -i br2 -s 192.168.0.0/24 -p tcp -j XRAY 2>/dev/null || true
iptables -t nat -D PREROUTING -i br2 -s 192.168.0.0/24 -p tcp -j XRAY 2>/dev/null || true
iptables -t nat -F XRAY 2>/dev/null
rm -f /var/tmp/vpnui/started_at /var/tmp/vpnui/xray.pid /var/LxC/vpnui.autostart

echo "=== vpn disabled ==="
echo "VPN/tunnel disabled. Panel/httpd untouched."
'''
out,err=run_ssh(cmd)
print(out)
if err: print("ERR:",err)
"@

$py | python -
