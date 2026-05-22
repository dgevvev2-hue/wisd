import paramiko, socket, time, sys
from pathlib import Path

HOST = "192.168.0.1"
USER = "superadmin"
PASSWORD = "8WHoDt3yCQR98BRx"

LOCAL_CONFIG = Path(__file__).parent / "vpnui" / "site" / "configs" / "external_simple.json"
REMOTE_CONFIG = "/var/tmp/vpnui/external.json"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, 22, username=USER, password=PASSWORD, timeout=15,
          banner_timeout=15, auth_timeout=15, look_for_keys=False,
          allow_agent=False, disabled_algorithms={'pubkeys': ['rsa-sha2-256', 'rsa-sha2-512']})

# Upload config to router using chunked printf method (like vpnui_push.py)
print("Uploading config to router...")
config_data = LOCAL_CONFIG.read_bytes()
CHUNK_BYTES = 200
n_chunks = max(1, (len(config_data) + CHUNK_BYTES - 1) // CHUNK_BYTES)
print(f"Uploading {len(config_data)} bytes in {n_chunks} chunks...")

# Create temp file
stage_tmp = REMOTE_CONFIG + ".tmp"
cmd = f"rm -f {stage_tmp}; echo __OK__"
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

# Write chunks
for i in range(n_chunks):
    chunk = config_data[i * CHUNK_BYTES : (i + 1) * CHUNK_BYTES]
    esc = "".join(f"\\x{b:02x}" for b in chunk)
    redir = ">" if i == 0 else ">>"
    cmd = f"/var/tmp/vpnui/bin/busybox-mips printf '%b' '{esc}' {redir} {stage_tmp}; echo __OK__"
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
    if "__OK__" not in out.decode("utf-8", errors="replace"):
        print(f"ERROR: Chunk {i+1}/{n_chunks} failed")
        c.close()
        sys.exit(1)
    if (i + 1) % 5 == 0 or i + 1 == n_chunks:
        print(f"  Chunk {i+1}/{n_chunks}")

# Atomic rename
cmd = f"mv {stage_tmp} {REMOTE_CONFIG}; echo __OK__"
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

if "__OK__" not in out.decode("utf-8", errors="replace"):
    print("ERROR: Config rename failed")
    c.close()
    sys.exit(1)

print("Config uploaded successfully")

# Stop existing xray
print("Stopping existing xray...")
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
print("xray stopped")

# Start xray with new config
print("Starting xray with external access config...")
cmd = f"/var/tmp/xray run -config {REMOTE_CONFIG} >/var/tmp/vpnui/xray.external.log 2>&1 &"
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

# Check if xray is running
time.sleep(2)
cmd = "ps | grep '[x]ray run'"
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

print("\nExternal access is now configured!")
print("  VLESS: 90.151.139.182:10086")
print("  UUID: da2ef6fd-107a-4985-bfe1-935b00b98cfb")
print("  Encryption: none")
print("  Transport: TCP")
print("\nUse v2rayN/v2rayNG client to connect.")

c.close()
