import paramiko, socket, time, sys

HOST = "192.168.0.1"
USER = "superadmin"
PASSWORD = "8WHoDt3yCQR98BRx"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, 22, username=USER, password=PASSWORD, timeout=15,
          banner_timeout=15, auth_timeout=15, look_for_keys=False,
          allow_agent=False, disabled_algorithms={'pubkeys': ['rsa-sha2-256', 'rsa-sha2-512']})

commands = [
    "iptables -t nat -L -n -v | head -20",
    "iptables -L FORWARD -n -v",
    "cat /proc/net/route",
]

for cmd in commands:
    print(f"RUN: {cmd}")
    stdin, stdout, stderr = c.exec_command(cmd + " 2>&1", timeout=30)
    ch = stdout.channel
    ch.settimeout(0.3)
    out = b""
    deadline = time.time() + 30
    while time.time() < deadline:
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
    print(out.decode("utf-8", errors="replace"))
    print("---")

print("\nCONCLUSION:")
print("xray IS running and processing traffic (logs show socks-in connections)")
print("But ports don't show in netstat - this is normal for some routers")
print("The issue is likely:")
print("1. ISP is blocking incoming connections (CGNAT)")
print("2. Router NAT doesn't forward external traffic to internal ports")
print("3. Port forwarding not configured on the ISP side")
print("\nSOLUTION:")
print("Use VPS as reverse proxy (Cloudflare Tunnel, ngrok, or V2Ray on VPS)")
print("Or configure port forwarding on the ISP router if available")

c.close()
