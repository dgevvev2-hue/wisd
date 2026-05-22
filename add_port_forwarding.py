import paramiko, socket, time, sys

HOST = "192.168.0.1"
USER = "superadmin"
PASSWORD = "8WHoDt3yCQR98BRx"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, 22, username=USER, password=PASSWORD, timeout=15,
          banner_timeout=15, auth_timeout=15, look_for_keys=False,
          allow_agent=False, disabled_algorithms={'pubkeys': ['rsa-sha2-256', 'rsa-sha2-512']})

# Add DNAT rules to forward external traffic to internal ports
print("Adding port forwarding rules...")
commands = [
    "iptables -t nat -I PREROUTING 1 -i ppp0.1 -p tcp --dport 1080 -j DNAT --to-destination 192.168.0.1:1080",
    "iptables -t nat -I PREROUTING 2 -i ppp0.1 -p tcp --dport 1081 -j DNAT --to-destination 192.168.0.1:1081",
    "iptables -t nat -I PREROUTING 3 -i ppp0.1 -p tcp --dport 8083 -j DNAT --to-destination 192.168.0.1:8083",
    "iptables -I FORWARD 1 -i ppp0.1 -d 192.168.0.1 -p tcp --dport 1080 -j ACCEPT",
    "iptables -I FORWARD 2 -i ppp0.1 -d 192.168.0.1 -p tcp --dport 1081 -j ACCEPT",
    "iptables -I FORWARD 3 -i ppp0.1 -d 192.168.0.1 -p tcp --dport 8083 -j ACCEPT",
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

# Check the rules were added
print("Checking NAT rules...")
cmd = "iptables -t nat -L PREROUTING -n -v | head -10"
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

print("\nPort forwarding added!")
print("External access should now work:")
print("  HTTP Proxy: 90.151.139.182:1081")
print("  SOCKS Proxy: 90.151.139.182:1080")
print("  Web Panel: 90.151.139.182:8083")

c.close()
