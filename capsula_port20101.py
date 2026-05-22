#!/usr/bin/env python3
"""
Targeted probe for the mystery TCP service on Capsula Mini :20101.

We don't know its protocol, so we try a battery of small payloads and
log exactly what the server says. Each probe uses a fresh TCP connection.

Probes performed (in order, sequentially with delay):
  1. Just connect, wait 2s for a banner.
  2. Plain TLS handshake (ClientHello) - is it HTTPS / mTLS / gRPC?
  3. HTTP/1.1 GET / and HEAD /
  4. HTTP/1.1 GET /info, /zc?action=getInfo, /api, /status
  5. WebSocket upgrade request.
  6. MQTT CONNECT packet (binary)
  7. Single newline / null byte / "PING\r\n"

Output -> capsula_port20101_results.json next to script.
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


def _connect(host, port, timeout=4.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((host, port))
    return s


def _recv_all(sock, max_bytes=4096, total_timeout=2.0):
    """Read whatever the server has within total_timeout."""
    sock.settimeout(0.5)
    chunks = []
    deadline = time.time() + total_timeout
    while time.time() < deadline and len(b"".join(chunks)) < max_bytes:
        try:
            chunk = sock.recv(max_bytes)
        except socket.timeout:
            if chunks:
                break
            continue
        except OSError:
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _format_response(raw):
    if not raw:
        return {"len": 0, "preview": "", "hex_head": ""}
    try:
        text = raw.decode("utf-8")
        printable = text
    except UnicodeDecodeError:
        printable = raw.decode("latin-1", errors="replace")
    return {
        "len": len(raw),
        "preview": printable[:600] + ("..." if len(printable) > 600 else ""),
        "hex_head": raw[:64].hex(),
    }


# ---------- individual probes ----------

def probe_silence(host, port):
    """Just connect and wait for an unsolicited banner."""
    try:
        s = _connect(host, port)
    except Exception as e:
        return {"name": "silence", "error": f"{type(e).__name__}: {e}"}
    raw = _recv_all(s, total_timeout=2.5)
    s.close()
    return {"name": "silence", "sent": "", **_format_response(raw)}


def probe_tls(host, port):
    """Full TLS handshake. Tells us if it's HTTPS/mTLS/gRPC over TLS."""
    try:
        sock = _connect(host, port, timeout=5.0)
    except Exception as e:
        return {"name": "tls", "error": f"{type(e).__name__}: {e}"}
    ctx = ssl._create_unverified_context()
    ctx.set_alpn_protocols(["h2", "http/1.1"])
    info = {"name": "tls"}
    try:
        ssock = ctx.wrap_socket(sock, server_hostname=host, do_handshake_on_connect=False)
        ssock.do_handshake()
        info["handshake"] = "OK"
        info["alpn"] = ssock.selected_alpn_protocol()
        info["cipher"] = ssock.cipher()
        info["version"] = ssock.version()
        try:
            cert = ssock.getpeercert(binary_form=False) or {}
            info["peer_cert"] = cert
            cert_der = ssock.getpeercert(binary_form=True)
            if cert_der:
                info["peer_cert_der_len"] = len(cert_der)
        except Exception as e:
            info["peer_cert_err"] = str(e)
        # try a tiny HTTP request through TLS
        try:
            ssock.sendall(b"GET / HTTP/1.0\r\nHost: " + host.encode() + b"\r\n\r\n")
            raw = _recv_all(ssock, total_timeout=2.0)
            info["tls_http_response"] = _format_response(raw)
        except Exception as e:
            info["tls_http_err"] = str(e)
        ssock.close()
    except ssl.SSLError as e:
        info["error"] = f"SSLError: {e}"
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
    return info


def probe_http(host, port, path, method="GET"):
    """Plain HTTP/1.1 request."""
    try:
        s = _connect(host, port)
    except Exception as e:
        return {"name": f"http_{method.lower()}_{path}", "error": f"{type(e).__name__}: {e}"}
    req = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"User-Agent: capsula-probe/1.0\r\n"
        f"Accept: */*\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()
    try:
        s.sendall(req)
        raw = _recv_all(s, total_timeout=3.0)
    except Exception as e:
        s.close()
        return {"name": f"http_{method.lower()}_{path}", "error": f"{type(e).__name__}: {e}"}
    s.close()
    return {"name": f"http_{method.lower()}_{path}", "sent": req.decode("ascii"),
            **_format_response(raw)}


def probe_websocket(host, port, path="/"):
    """RFC-6455 WebSocket upgrade request."""
    try:
        s = _connect(host, port)
    except Exception as e:
        return {"name": "websocket", "error": f"{type(e).__name__}: {e}"}
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"Origin: http://{host}\r\n\r\n"
    ).encode()
    try:
        s.sendall(req)
        raw = _recv_all(s, total_timeout=2.0)
    except Exception as e:
        s.close()
        return {"name": "websocket", "error": f"{type(e).__name__}: {e}"}
    s.close()
    return {"name": "websocket", "sent": req.decode("ascii"), **_format_response(raw)}


def probe_mqtt(host, port):
    """MQTT 3.1.1 CONNECT packet. If MQTT, server replies with CONNACK."""
    # Fixed header: 0x10 (CONNECT)
    # Variable header: protocol name "MQTT" (0x0004 'MQTT'), level 4, flags 0x02 (clean), keepalive 60
    # Payload: client id "capsula-probe"
    cid = b"capsula-probe"
    var = b"\x00\x04MQTT\x04\x02\x00\x3c"
    payload = len(cid).to_bytes(2, "big") + cid
    body = var + payload
    pkt = b"\x10" + bytes([len(body)]) + body
    try:
        s = _connect(host, port)
    except Exception as e:
        return {"name": "mqtt", "error": f"{type(e).__name__}: {e}"}
    try:
        s.sendall(pkt)
        raw = _recv_all(s, total_timeout=2.0)
    except Exception as e:
        s.close()
        return {"name": "mqtt", "error": f"{type(e).__name__}: {e}"}
    s.close()
    return {"name": "mqtt", "sent_hex": pkt.hex(), **_format_response(raw)}


def probe_raw(host, port, payload, name):
    try:
        s = _connect(host, port)
    except Exception as e:
        return {"name": name, "error": f"{type(e).__name__}: {e}"}
    try:
        s.sendall(payload)
        raw = _recv_all(s, total_timeout=2.0)
    except Exception as e:
        s.close()
        return {"name": name, "error": f"{type(e).__name__}: {e}"}
    s.close()
    return {"name": name, "sent_hex": payload.hex(), **_format_response(raw)}


# ---------- driver ----------

def run(host, port, delay):
    print(f"=== Probing {host}:{port} ===\n")
    findings = []

    def log(r):
        findings.append(r)
        name = r.get("name", "?")
        if r.get("error"):
            print(f"  [{name}] ERROR: {r['error']}")
        else:
            extras = []
            for k in ("alpn", "version", "cipher", "handshake"):
                if k in r:
                    extras.append(f"{k}={r[k]}")
            extras_str = (" " + " ".join(extras)) if extras else ""
            print(f"  [{name}] len={r.get('len', '?')}{extras_str}")
            preview = r.get("preview", "") or ""
            preview = preview.replace("\r", "\\r").replace("\n", "\\n")[:200]
            if preview:
                print(f"      preview: {preview}")
            if r.get("hex_head") and r.get("len", 0) > 0:
                print(f"      hex[:32]: {r['hex_head'][:64]}")
            if r.get("peer_cert"):
                print(f"      peer_cert: {json.dumps(r['peer_cert'])[:200]}")
            if r.get("tls_http_response"):
                tr = r["tls_http_response"]
                p = (tr.get("preview") or "").replace("\r", "\\r").replace("\n", "\\n")[:200]
                print(f"      tls-http preview: {p}")
        time.sleep(delay)

    log(probe_silence(host, port))
    log(probe_tls(host, port))
    log(probe_http(host, port, "/"))
    log(probe_http(host, port, "/", method="HEAD"))
    log(probe_http(host, port, "/info"))
    log(probe_http(host, port, "/zc?action=getInfo&version=2.10.0"))
    log(probe_http(host, port, "/api"))
    log(probe_http(host, port, "/status"))
    log(probe_http(host, port, "/version"))
    log(probe_http(host, port, "/health"))
    log(probe_websocket(host, port, "/"))
    log(probe_websocket(host, port, "/ws"))
    log(probe_websocket(host, port, "/api"))
    log(probe_mqtt(host, port))
    log(probe_raw(host, port, b"\r\n", "newline"))
    log(probe_raw(host, port, b"\x00", "nullbyte"))
    log(probe_raw(host, port, b"PING\r\n", "ping_text"))
    log(probe_raw(host, port, b"INFO\r\n", "info_text"))
    log(probe_raw(host, port, b"\xff\xff\xff\xff", "binary_ff"))
    log(probe_raw(host, port, b"HELO " + host.encode() + b"\r\n", "smtp_helo"))

    return findings


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.join(script_dir, "capsula_port20101_results.json")

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--delay", type=float, default=0.6,
                    help="seconds between probes")
    ap.add_argument("--out", default=default_out)
    args = ap.parse_args()

    out_path = os.path.abspath(args.out)
    print(f"Capsula Mini port-{args.port} probe -> {args.host}")
    print(f"Will write results to: {out_path}\n")

    started = time.time()
    out = {"host": args.host, "port": args.port, "started_at": started}
    try:
        out["probes"] = run(args.host, args.port, args.delay)
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
