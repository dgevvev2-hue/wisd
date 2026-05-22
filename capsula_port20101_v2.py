#!/usr/bin/env python3
"""
Deeper probe of :20101.

First pass said:
  - silent on connect
  - TLS handshake -> RST
  - other small payloads -> 0 bytes back, server holds connection

This pass tests stronger hypotheses:
  - TLS with explicit SNIs (marusia.mail.ru, voice.mail.ru, hostname,
    *.vk.com, ip-as-name) and longer handshake timeout
  - Long silent wait (30s) - maybe server pushes heartbeat / hello
  - HTTP/2 prior knowledge (cleartext h2c preface)
  - Multiple sequential connects to detect rate-limit / connection cap
  - Slow-byte send: ClientHello sent one byte every 100ms

Output: capsula_port20101_v2_results.json
"""
import argparse
import json
import os
import socket
import ssl
import sys
import time

DEFAULT_HOST = "192.168.0.11"
DEFAULT_PORT = 20101

H2_PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"

# SNI candidates - these are typical Marusia / VK / Mail.ru endpoints
SNI_LIST = [
    None,                         # no SNI at all
    "192.168.0.11",
    "Capsula-mini-03447D709FE0FBAE",
    "capsula-mini",
    "marusia.mail.ru",
    "voice.mail.ru",
    "marusia-api.mail.ru",
    "device.marusia.mail.ru",
    "vk.com",
    "mail.ru",
    "iot.mail.ru",
    "speaker.mail.ru",
]


def _connect(host, port, timeout=6.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((host, port))
    return s


def _recv_for(sock, total_seconds, max_bytes=8192):
    sock.settimeout(0.5)
    chunks = []
    deadline = time.time() + total_seconds
    while time.time() < deadline and len(b"".join(chunks)) < max_bytes:
        try:
            ch = sock.recv(max_bytes)
        except socket.timeout:
            continue
        except OSError as e:
            return {"data": b"".join(chunks), "closed": True, "err": str(e)}
        if not ch:
            return {"data": b"".join(chunks), "closed": True, "err": None}
        chunks.append(ch)
    return {"data": b"".join(chunks), "closed": False, "err": None}


def _format(raw):
    if not raw:
        return {"len": 0, "preview": "", "hex_head": ""}
    return {
        "len": len(raw),
        "preview": raw.decode("latin-1", errors="replace")[:600],
        "hex_head": raw[:64].hex(),
    }


# ---------- Probes ----------

def probe_long_silence(host, port, seconds=30):
    """Hold the connection open for up to N seconds, see if server pushes."""
    name = f"long_silence_{seconds}s"
    print(f"  [{name}] connecting + waiting...")
    try:
        s = _connect(host, port)
    except Exception as e:
        return {"name": name, "error": f"{type(e).__name__}: {e}"}
    r = _recv_for(s, total_seconds=seconds)
    s.close()
    return {"name": name, "closed_by_peer": r["closed"], "recv_err": r["err"],
            **_format(r["data"])}


def probe_tls_sni(host, port, sni, alpns=("h2", "http/1.1"), timeout=8.0):
    name = f"tls_sni={sni}_alpn={'+'.join(alpns)}"
    info = {"name": name, "sni": sni, "alpns": list(alpns)}
    try:
        sock = _connect(host, port, timeout=timeout)
    except Exception as e:
        info["error"] = f"connect: {type(e).__name__}: {e}"
        return info
    sock.settimeout(timeout)
    ctx = ssl._create_unverified_context()
    if alpns:
        try:
            ctx.set_alpn_protocols(list(alpns))
        except NotImplementedError:
            pass
    try:
        ssock = ctx.wrap_socket(sock, server_hostname=sni,
                                do_handshake_on_connect=False)
        ssock.do_handshake()
        info["handshake"] = "OK"
        info["alpn"] = ssock.selected_alpn_protocol()
        info["tls_version"] = ssock.version()
        info["cipher"] = ssock.cipher()
        try:
            cert = ssock.getpeercert(binary_form=False) or {}
            info["peer_cert"] = cert
        except Exception as e:
            info["peer_cert_err"] = str(e)
        try:
            cert_der = ssock.getpeercert(binary_form=True) or b""
            info["peer_cert_der_len"] = len(cert_der)
        except Exception:
            pass
        ssock.close()
    except ssl.SSLError as e:
        info["error"] = f"SSLError: {e}"
    except ConnectionResetError as e:
        info["error"] = f"RST: {e}"
    except socket.timeout:
        info["error"] = "timeout"
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
    return info


def probe_h2c(host, port):
    """HTTP/2 cleartext prior-knowledge preface."""
    name = "h2c_preface"
    try:
        s = _connect(host, port)
    except Exception as e:
        return {"name": name, "error": f"{type(e).__name__}: {e}"}
    try:
        s.sendall(H2_PREFACE)
        # add a SETTINGS frame (empty) as a real h2 client would
        # frame: length(3)=0, type(1)=0x04 SETTINGS, flags(1)=0, stream(4)=0
        s.sendall(b"\x00\x00\x00\x04\x00\x00\x00\x00\x00")
        r = _recv_for(s, total_seconds=4.0)
    except Exception as e:
        s.close()
        return {"name": name, "error": f"{type(e).__name__}: {e}"}
    s.close()
    return {"name": name, "closed_by_peer": r["closed"], "recv_err": r["err"],
            **_format(r["data"])}


def probe_slow_clienthello(host, port):
    """Send a TLS ClientHello byte-by-byte to see if the RST is timing-based."""
    name = "tls_slow_byte_by_byte"
    try:
        s = _connect(host, port)
    except Exception as e:
        return {"name": name, "error": f"{type(e).__name__}: {e}"}
    # Build a minimal TLS 1.2 ClientHello (no extensions for simplicity).
    # 0x16 = handshake, 0x03 0x01 = TLS 1.0 record version (universal),
    # then TLS handshake message: 0x01 ClientHello.
    # We'll just borrow openssl's standard hello via wrap -> writes; but to
    # do true byte-by-byte we synthesise a small one:
    body = (
        b"\x03\x03"                                 # client_version TLS 1.2
        + os.urandom(32)                            # random
        + b"\x00"                                   # session id len
        + b"\x00\x02\x00\x35"                       # cipher suites: AES256-SHA
        + b"\x01\x00"                               # compression methods: null
        + b"\x00\x00"                               # extensions length 0
    )
    handshake = b"\x01\x00" + len(body).to_bytes(2, "big") + body  # type 0x01
    record = b"\x16\x03\x01" + len(handshake).to_bytes(2, "big") + handshake
    try:
        for b in record:
            s.sendall(bytes([b]))
            time.sleep(0.05)
        r = _recv_for(s, total_seconds=3.0)
    except Exception as e:
        s.close()
        return {"name": name, "error": f"{type(e).__name__}: {e}"}
    s.close()
    return {"name": name, "closed_by_peer": r["closed"], "recv_err": r["err"],
            **_format(r["data"])}


def probe_repeated_connect(host, port, n=5, gap=0.5):
    """Open and immediately close N times; report which succeeded."""
    name = f"repeated_connect_x{n}"
    results = []
    for i in range(n):
        ok = False
        err = None
        t0 = time.time()
        try:
            s = _connect(host, port, timeout=3.0)
            s.close()
            ok = True
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        results.append({"i": i, "ok": ok, "err": err,
                        "ms": int((time.time() - t0) * 1000)})
        time.sleep(gap)
    return {"name": name, "results": results}


# ---------- driver ----------

def run(host, port, long_wait):
    print(f"=== Deeper probe {host}:{port} ===\n")
    findings = []

    def log(r):
        findings.append(r)
        name = r.get("name", "?")
        if r.get("error"):
            print(f"  [{name}] ERROR: {r['error']}")
            return
        line = f"  [{name}]"
        for k in ("handshake", "alpn", "tls_version", "peer_cert_der_len",
                  "closed_by_peer", "len"):
            if k in r:
                line += f" {k}={r[k]}"
        print(line)
        if r.get("cipher"):
            print(f"      cipher: {r['cipher']}")
        if r.get("peer_cert"):
            cs = json.dumps(r["peer_cert"])[:300]
            print(f"      peer_cert: {cs}")
        preview = (r.get("preview") or "")
        if preview:
            preview = preview.replace("\r", "\\r").replace("\n", "\\n")[:200]
            print(f"      preview: {preview}")
        if r.get("hex_head") and r.get("len", 0) > 0:
            print(f"      hex[:32]: {r['hex_head'][:64]}")
        if r.get("results"):
            for rr in r["results"]:
                print(f"      conn#{rr['i']} ok={rr['ok']} ms={rr['ms']} err={rr['err']}")

    # 1) Repeated connects to see if port stays consistently up
    log(probe_repeated_connect(host, port, n=4, gap=0.4))
    time.sleep(0.5)

    # 2) Long silent wait - does server send heartbeat?
    log(probe_long_silence(host, port, seconds=long_wait))
    time.sleep(0.5)

    # 3) HTTP/2 cleartext prior-knowledge
    log(probe_h2c(host, port))
    time.sleep(0.5)

    # 4) TLS with various SNIs
    for sni in SNI_LIST:
        log(probe_tls_sni(host, port, sni=sni, alpns=("h2", "http/1.1")))
        time.sleep(0.4)

    # 5) TLS with only http/1.1 (some servers reject if h2 demanded)
    log(probe_tls_sni(host, port, sni="marusia.mail.ru", alpns=("http/1.1",)))
    time.sleep(0.4)

    # 6) TLS with no ALPN (closest to legacy clients)
    log(probe_tls_sni(host, port, sni="marusia.mail.ru", alpns=()))
    time.sleep(0.4)

    # 7) Slow byte-by-byte TLS handshake - probes timing-based RST
    log(probe_slow_clienthello(host, port))
    time.sleep(0.4)

    return findings


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.join(script_dir, "capsula_port20101_v2_results.json")

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--long-wait", type=int, default=30,
                    help="seconds to silently wait for unsolicited push")
    ap.add_argument("--out", default=default_out)
    args = ap.parse_args()

    out_path = os.path.abspath(args.out)
    print(f"Capsula Mini :{args.port} v2 probe -> {args.host}")
    print(f"Output: {out_path}\n")

    started = time.time()
    out = {"host": args.host, "port": args.port, "started_at": started}
    try:
        out["probes"] = run(args.host, args.port, args.long_wait)
    except KeyboardInterrupt:
        print("\n[interrupted]")
        out["interrupted"] = True
    except Exception as e:
        print(f"\n[error] {type(e).__name__}: {e}")
        out["error"] = f"{type(e).__name__}: {e}"
    finally:
        out["elapsed_sec"] = round(time.time() - started, 2)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n[saved] {out_path} ({os.path.getsize(out_path)} bytes)")
    print(f"\nDone in {out['elapsed_sec']}s")


if __name__ == "__main__":
    sys.exit(main())
