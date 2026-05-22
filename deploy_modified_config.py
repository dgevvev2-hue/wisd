import paramiko, socket, time, sys
from pathlib import Path

HOST = "192.168.0.1"
USER = "superadmin"
PASSWORD = "8WHoDt3yCQR98BRx"

LOCAL_CONFIG = Path(__file__).parent / "vpnui" / "site" / "configs" / "1.json"
REMOTE_CONFIG = "/var/tmp/vpnui/active.json"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, 22, username=USER, password=PASSWORD, timeout=15,
          banner_timeout=15, auth_timeout=15, look_for_keys=False,
          allow_agent=False, disabled_algorithms={'pubkeys': ['rsa-sha2-256', 'rsa-sha2-512']})

# Upload config to router using chunked printf method
print("Uploading modified config to router...")
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

print("\nExternal access now configured:")
print("  HTTP Proxy: 90.151.139.182:1081")
print("  SOCKS Proxy: 90.151.139.182:1080")
print("\nWARNING: No authentication! Anyone can access.")

c.close()
