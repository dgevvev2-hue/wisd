import paramiko, socket, time, sys

HOST = "192.168.0.1"
USER = "superadmin"
PASSWORD = "8WHoDt3yCQR98BRx"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, 22, username=USER, password=PASSWORD, timeout=15,
          banner_timeout=15, auth_timeout=15, look_for_keys=False,
          allow_agent=False, disabled_algorithms={'pubkeys': ['rsa-sha2-256', 'rsa-sha2-512']})

# Modify the active config to change HTTP proxy listen from 192.168.0.1 to 0.0.0.0
print("Modifying active config to listen on 0.0.0.0:1081...")
cmd = "sed -i 's/192.168.0.1:1081/0.0.0.0:1081/g' /var/tmp/vpnui/active.json"
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

# Also change SOCKS to 0.0.0.0
print("Modifying SOCKS proxy to listen on 0.0.0.0:1080...")
cmd = "sed -i 's/192.168.0.1:1080/0.0.0.0:1080/g' /var/tmp/vpnui/active.json"
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

# Restart xray
print("Restarting xray...")
cmd = "killall xray 2>/dev/null || true"
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

time.sleep(2)

cmd = "/var/tmp/xray run -config /var/tmp/vpnui/active.json >/var/tmp/vpnui/xray.log 2>&1 &"
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

time.sleep(2)

# Check listening ports
print("Checking listening ports...")
cmd = "netstat -an | grep -E '1080|1081'"
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

print("\nExternal access now available:")
print("  HTTP Proxy: 90.151.139.182:1081")
print("  SOCKS Proxy: 90.151.139.182:1080")
print("\nWARNING: No authentication! Anyone can access.")

c.close()
