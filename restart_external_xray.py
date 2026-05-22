import paramiko, socket, time, sys

HOST = "192.168.0.1"
USER = "superadmin"
PASSWORD = "8WHoDt3yCQR98BRx"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, 22, username=USER, password=PASSWORD, timeout=15,
          banner_timeout=15, auth_timeout=15, look_for_keys=False,
          allow_agent=False, disabled_algorithms={'pubkeys': ['rsa-sha2-256', 'rsa-sha2-512']})

# Kill all xray processes
print("Killing all xray processes...")
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
print("xray killed")

time.sleep(2)

# Start xray with external config
print("Starting xray with external config...")
cmd = "/var/tmp/xray run -config /var/tmp/vpnui/external.json >/var/tmp/vpnui/xray.external.log 2>&1 &"
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
print("xray started")

time.sleep(2)

# Check if xray is running
print("Checking xray status...")
cmd = "ps | grep '[x]ray'"
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

# Check listening ports
print("Checking listening ports...")
cmd = "netstat -an | grep LISTEN"
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

c.close()
