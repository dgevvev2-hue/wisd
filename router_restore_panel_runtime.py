import sys, time, socket

HOST = "192.168.0.1"
USER = "superadmin"
PASSWORD = "8WHoDt3yCQR98BRx"

try:
    import paramiko
except Exception as e:
    print("Paramiko import failed:", e)
    sys.exit(2)

COMMANDS = [
    "mkdir -p /var/usbmnt/sda1 /var/tmp/vpnui/bin /var/tmp/vpnui/www",
    "mount | grep '/var/usbmnt/sda1' >/dev/null || mount -t ext2 /dev/sda1 /var/usbmnt/sda1",
    "cp /var/usbmnt/sda1/vpnui/bin/busybox-mips /var/tmp/vpnui/bin/busybox-mips",
    "cp /var/usbmnt/sda1/vpnui/bin/rwget /var/tmp/vpnui/bin/rwget 2>/dev/null || true",
    "cp /var/usbmnt/sda1/vpnui/bin/sftp-server /var/tmp/vpnui/bin/sftp-server 2>/dev/null || true",
    "[ -x /var/tmp/xray ] || cp /var/usbmnt/sda1/vpnui/xray /var/tmp/xray",
    "cp /var/usbmnt/sda1/vpnui/geoip.dat /var/tmp/vpnui/geoip.dat 2>/dev/null || true",
    "cp /var/usbmnt/sda1/vpnui/geosite.dat /var/tmp/vpnui/geosite.dat 2>/dev/null || true",
    "rm -rf /var/tmp/vpnui/www && mkdir -p /var/tmp/vpnui/www && cp -a /var/usbmnt/sda1/vpnui/www/. /var/tmp/vpnui/www/",
    "chmod +x /var/tmp/vpnui/bin/* /var/tmp/xray /var/tmp/vpnui/www/cgi-bin/*.cgi 2>/dev/null || true",
    "ps | grep '/var/tmp/vpnui/bin/busybox-mips httpd' | grep -v grep | awk '{print $1}' | xargs kill -9 2>/dev/null || true",
    "/var/tmp/vpnui/bin/busybox-mips httpd -f -p 192.168.0.1:8083 -h /var/tmp/vpnui/www >/var/tmp/vpnui/httpd.log 2>&1 &",
    "iptables -C INPUT -i br2 -p tcp --dport 8083 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -i br2 -p tcp --dport 8083 -j ACCEPT",
    "echo Panel restored. VPN tunnel was NOT started.",
]

def prefer(sec, name, wanted):
    if not hasattr(sec, name):
        return
    current = list(getattr(sec, name))
    ordered = [x for x in wanted if x in current] + [x for x in current if x not in wanted]
    if ordered:
        setattr(sec, name, ordered)

def connect():
    last = None
    for attempt in range(1, 6):
        try:
            sock = socket.create_connection((HOST, 22), timeout=15)
            t = paramiko.Transport(sock)
            sec = t.get_security_options()
            prefer(sec, "kex", ["diffie-hellman-group1-sha1", "diffie-hellman-group14-sha1"])
            prefer(sec, "key_types", ["ssh-rsa"])
            prefer(sec, "ciphers", ["aes128-cbc", "3des-cbc", "aes256-cbc", "aes128-ctr"])
            prefer(sec, "digests", ["hmac-sha1", "hmac-sha1-96", "hmac-md5"])
            t.start_client(timeout=20)
            t.auth_password(USER, PASSWORD)
            if not t.is_authenticated():
                raise RuntimeError("SSH password auth failed")
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c._transport = t
            return c
        except Exception as e:
            last = e
            try:
                sock.close()
            except Exception:
                pass
            print(f"SSH connect attempt {attempt}/5 failed: {e}")
            time.sleep(2)
    raise last

def run(c, cmd, timeout=25):
    print("RUN:", cmd)
    stdin, stdout, stderr = c.exec_command(cmd + " 2>&1", timeout=timeout)
    ch = stdout.channel
    ch.settimeout(0.3)
    out = b""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if ch.recv_ready():
                out += ch.recv(4096)
        except socket.timeout:
            pass
        if ch.exit_status_ready():
            while ch.recv_ready():
                out += ch.recv(4096)
            break
        time.sleep(0.1)
    try:
        rc = ch.recv_exit_status() if ch.exit_status_ready() else 0
    except Exception:
        rc = 0
    text = out.decode("utf-8", "replace").strip()
    if text:
        print(text)
    return rc

def main():
    c = connect()
    try:
        for cmd in COMMANDS:
            rc = run(c, cmd)
            if rc not in (0, None):
                print(f"Command returned rc={rc}, continuing.")
    finally:
        c.close()
    print("")
    print("Done. Open: http://192.168.0.1:8083/")

if __name__ == "__main__":
    main()
