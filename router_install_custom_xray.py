import http.server
import os
import shutil
import socket
import socketserver
import tempfile
import threading
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent
HOST = "192.168.0.1"
USER = "superadmin"
PASSWORD = "8WHoDt3yCQR98BRx"
BB = "/var/tmp/vpnui/bin/busybox-mips"

CANDIDATES = [
    ROOT / "xray_custom_v24.11.30_mips_hardfloat",
    ROOT / "xray_custom_v24.11.30_mips_softfloat",
]


def prefer(sec, name, wanted):
    if not hasattr(sec, name):
        return
    cur = list(getattr(sec, name))
    out = [x for x in wanted if x in cur] + [x for x in cur if x not in wanted]
    if out:
        setattr(sec, name, out)


def open_client():
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


def run_ssh(cmd, timeout=90):
    c = open_client()
    try:
        _, stdout, _ = c.exec_command(cmd + " 2>&1", timeout=timeout)
        ch = stdout.channel
        ch.settimeout(0.4)
        buf = b""
        end = time.time() + timeout
        while time.time() < end:
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
        code = ch.recv_exit_status() if ch.exit_status_ready() else 124
        return code, buf.decode("utf-8", "replace")
    finally:
        c.close()


def local_ip_to_router():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((HOST, 80))
        return s.getsockname()[0]
    finally:
        s.close()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass


def serve(path):
    class ReuseTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    old = os.getcwd()
    os.chdir(path)
    srv = ReuseTCPServer(("0.0.0.0", 0), QuietHandler)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, port, old


def fetch_and_test(ip, port):
    url = f"http://{ip}:{port}/xray"
    cmd = f"""
set -e
rm -f /var/tmp/xray.new /var/tmp/xray.new.version
({BB} wget -O /var/tmp/xray.new {url} || wget -O /var/tmp/xray.new {url})
chmod +x /var/tmp/xray.new
/var/tmp/xray.new version >/var/tmp/xray.new.version 2>&1
cat /var/tmp/xray.new.version
"""
    return run_ssh(cmd, timeout=180)


def install_tested():
    cmd = """
set -e
mkdir -p /var/tmp/vpnui /var/usbmnt/sda1/vpnui
killall xray 2>/dev/null || true
cp /var/tmp/xray /var/tmp/vpnui/xray.bak.before-custom 2>/dev/null || true
cp /var/usbmnt/sda1/vpnui/xray /var/usbmnt/sda1/vpnui/xray.bak.before-custom 2>/dev/null || true
cp /var/tmp/xray.new /var/tmp/xray
cp /var/tmp/xray.new /var/usbmnt/sda1/vpnui/xray
chmod +x /var/tmp/xray /var/usbmnt/sda1/vpnui/xray
/var/tmp/xray version
echo INSTALLED_CUSTOM_XRAY_OK
"""
    return run_ssh(cmd, timeout=600)


def main():
    for p in CANDIDATES:
        if not p.exists():
            raise FileNotFoundError(p)

    print("Current router Xray:")
    print(run_ssh("/var/tmp/xray version || true", timeout=30)[1].strip())
    ip = local_ip_to_router()
    print("PC LAN IP:", ip)

    with tempfile.TemporaryDirectory(prefix="xray-serve-") as tmp:
        tmp = Path(tmp)
        for candidate in CANDIDATES:
            print("Testing", candidate.name)
            shutil.copyfile(candidate, tmp / "xray")
            srv, port, old = serve(tmp)
            try:
                code, out = fetch_and_test(ip, port)
            finally:
                srv.shutdown()
                srv.server_close()
                os.chdir(old)
            print(out.strip())
            bad = "SIGSEGV" in out or "futexwakeup" in out or "applet not found" in out
            if code == 0 and "Xray " in out and not bad:
                print("Installing", candidate.name)
                code, out = install_tested()
                print(out.strip())
                if code != 0 or "INSTALLED_CUSTOM_XRAY_OK" not in out:
                    raise RuntimeError("install failed: " + out[-1000:])
                return
            print("Not compatible, trying next.")
    raise RuntimeError("No custom build worked on router.")


if __name__ == "__main__":
    main()
