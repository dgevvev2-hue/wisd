#!/usr/bin/env python3
"""
:20101 probe v3 - exhaust the remaining hypotheses.

What v1+v2 told us:
  - port stays open & stable
  - nothing is pushed unsolicited (30s wait => silence)
  - TLS ClientHello (any SNI, any ALPN, byte-by-byte) => RST
  - h2c preface ("PRI * HTTP/2.0...") => peer FINs after read
  - small junk payloads => server holds open, no reply (parser waits)

That fingerprint = framed binary protocol with a magic header
OR a slow vendor HTTP server that needs >3s to reply.

This pass tries:
  A) Plain HTTP/1.1 GET with LONG recv timeout (30s) on a few paths.
  B) HTTP with the speaker's identity strings as auth (deviceID, serial).
  C) Length-prefixed binary frames: 4-byte big-endian length + payload.
  D) "Magic-byte" sweep: open conn, send 1 byte (0x00..0xFF), wait 1.5s,
     log if peer sent anything before our timeout. Reveals first-byte
     dispatch logic.
  E) Half-close mode: connect, shutdown(WR), see if peer responds when
     it knows we won't send more.

Output: capsula_port20101_v3_results.json
"""
import argparse
import json
import os
import socket
import struct
import sys
import time

DEFAULT_HOST = "192.168.0.11"
DEFAULT_PORT = 20101


def _connect(host, port, timeout=8.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((host, port))
    return s


def _recv_for(sock, total_seconds, max_bytes=8192):
    sock.settimeout(0.4)
    chunks = []
    deadline = time.time() + total_seconds
    rst = False
    closed = False
    while time.time() < deadline and len(b"".join(chunks)) < max_bytes:
        try:
            ch = sock.recv(max_bytes)
        except socket.timeout:
            continue
        except ConnectionResetError:
            rst = True
            break
        except OSError:
            break
        if not ch:
            closed = True
            break
        chunks.append(ch)
    return {"data": b"".join(chunks), "closed": closed, "rst": rst}


def _fmt(raw):
    if not raw:
        return {"len": 0, "preview": "", "hex_head": ""}
    return {"len": len(raw),
            "preview": raw.decode("latin-1", errors="replace")[:400],
            "hex_head": raw[:64].hex()}


# --- A: plain HTTP with long timeout ----------------------------------------

def probe_http_long(host, port, path, wait):
    name = f"http_long_{path}"
    try:
        s = _connect(host, port)
    except Exception as e:
        return {"name": name, "error": f"{type(e).__name__}: {e}"}
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"User-Agent: Marusia/1.0\r\n"
        f"Accept: */*\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()
    try:
        s.sendall(req)
    except Exception as e:
        s.close()
        return {"name": name, "error": f"send: {e}"}
    r = _recv_for(s, total_seconds=wait)
    s.close()
    return {"name": name, "wait_s": wait, **r, **_fmt(r["data"])}


def probe_http_with_id(host, port, device_id, serial, wait):
    """Try HTTP with the device's own identifiers as Authorization headers."""
    name = "http_with_device_id"
    try:
        s = _connect(host, port)
    except Exception as e:
        return {"name": name, "error": f"{type(e).__name__}: {e}"}
    req = (
        f"GET / HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"User-Agent: Marusia/1.0\r\n"
        f"X-Device-Id: {device_id}\r\n"
        f"X-Serial: {serial}\r\n"
        f"Authorization: Bearer {device_id}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()
    try:
        s.sendall(req)
    except Exception as e:
        s.close()
        return {"name": name, "error": f"send: {e}"}
    r = _recv_for(s, total_seconds=wait)
    s.close()
    return {"name": name, "wait_s": wait, **r, **_fmt(r["data"])}


# --- C: length-prefixed binary frames ---------------------------------------

def probe_lenprefix(host, port, payload, wait, name):
    try:
        s = _connect(host, port)
    except Exception as e:
        return {"name": name, "error": f"{type(e).__name__}: {e}"}
    pkt = struct.pack("!I", len(payload)) + payload
    try:
        s.sendall(pkt)
    except Exception as e:
        s.close()
        return {"name": name, "error": f"send: {e}"}
    r = _recv_for(s, total_seconds=wait)
    s.close()
    return {"name": name, "sent_hex": pkt.hex(), **r, **_fmt(r["data"])}


# --- D: first-byte sweep ----------------------------------------------------

def probe_first_byte_sweep(host, port, recv_wait=1.2):
    name = "first_byte_sweep"
    print(f"  [{name}] sending 1 byte 0x00..0xFF, recv_wait={recv_wait}s each "
          f"(this takes ~{256 * (recv_wait + 0.3):.0f}s)")
    interesting = []
    for b in range(256):
        try:
            s = _connect(host, port, timeout=3.0)
        except Exception:
            interesting.append({"byte": b, "error": "connect"})
            continue
        try:
            s.sendall(bytes([b]))
        except Exception:
            s.close()
            continue
        r = _recv_for(s, total_seconds=recv_wait)
        s.close()
        if r["data"] or r["rst"] or r["closed"]:
            entry = {
                "byte": b,
                "hex": f"0x{b:02x}",
                "len": len(r["data"]),
                "rst": r["rst"],
                "closed": r["closed"],
                "hex_head": r["data"][:32].hex(),
            }
            interesting.append(entry)
            tag = "DATA" if r["data"] else ("RST" if r["rst"] else "FIN")
            print(f"      0x{b:02x}  {tag}  data_len={len(r['data'])}"
                  + (f"  hex={r['data'][:32].hex()}" if r["data"] else ""))
    return {"name": name, "results": interesting,
            "summary": f"{len(interesting)} of 256 bytes triggered a reaction"}


# --- E: half-close ----------------------------------------------------------

def probe_halfclose(host, port, wait):
    name = "halfclose_then_wait"
    try:
        s = _connect(host, port)
    except Exception as e:
        return {"name": name, "error": f"{type(e).__name__}: {e}"}
    try:
        s.shutdown(socket.SHUT_WR)
    except Exception as e:
        s.close()
        return {"name": name, "error": f"shutdown: {e}"}
    r = _recv_for(s, total_seconds=wait)
    s.close()
    return {"name": name, "wait_s": wait, **r, **_fmt(r["data"])}


# --- driver -----------------------------------------------------------------

def run(host, port, http_wait, frame_wait, do_byte_sweep,
        device_id, serial):
    findings = []

    def log(r):
        findings.append(r)
        name = r.get("name", "?")
        if r.get("error"):
            print(f"  [{name}] ERROR: {r['error']}")
            return
        line = f"  [{name}]"
        for k in ("wait_s", "len", "closed", "rst"):
            if k in r:
                line += f" {k}={r[k]}"
        if "summary" in r:
            line += f"  -> {r['summary']}"
        print(line)
        if r.get("preview"):
            p = r["preview"].replace("\r", "\\r").replace("\n", "\\n")[:200]
            print(f"      preview: {p}")
        if r.get("hex_head") and r.get("len", 0) > 0:
            print(f"      hex[:32]: {r['hex_head'][:64]}")

    # A: long HTTP
    for path in ("/", "/info", "/api", "/v1/info", "/zc?action=getInfo"):
        log(probe_http_long(host, port, path, http_wait))
        time.sleep(0.4)

    # B: HTTP with device id headers
    log(probe_http_with_id(host, port, device_id, serial, http_wait))
    time.sleep(0.4)

    # C: length-prefixed frames
    for tag, payload in [
        ("lenpref_empty", b""),
        ("lenpref_HELLO", b"HELLO"),
        ("lenpref_INFO_json", b'{"action":"getInfo"}'),
        ("lenpref_AUTH", b'{"auth":"' + device_id.encode() + b'"}'),
        ("lenpref_PING", b"PING"),
        ("lenpref_serial", serial.encode()),
    ]:
        log(probe_lenprefix(host, port, payload, frame_wait, tag))
        time.sleep(0.4)

    # E: half-close
    log(probe_halfclose(host, port, http_wait))
    time.sleep(0.4)

    # D: first-byte sweep (last - it's the slowest and noisiest)
    if do_byte_sweep:
        log(probe_first_byte_sweep(host, port, recv_wait=1.0))

    return findings


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.join(script_dir, "capsula_port20101_v3_results.json")

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--http-wait", type=float, default=20.0,
                    help="seconds to wait for HTTP response (default 20)")
    ap.add_argument("--frame-wait", type=float, default=5.0,
                    help="seconds to wait after framed binary send")
    ap.add_argument("--device-id",
                    default=":c:d:capsula_mini:ea9928e2b4fe131b33673fdbac263d77")
    ap.add_argument("--serial", default="03447D709FE0FBAE")
    ap.add_argument("--no-byte-sweep", action="store_true",
                    help="skip the 256-byte first-byte sweep (~5 min)")
    ap.add_argument("--out", default=default_out)
    args = ap.parse_args()

    out_path = os.path.abspath(args.out)
    print(f"Capsula Mini :{args.port} v3 probe -> {args.host}")
    print(f"Output: {out_path}\n")

    started = time.time()
    out = {"host": args.host, "port": args.port, "started_at": started}
    try:
        out["probes"] = run(
            args.host, args.port, args.http_wait, args.frame_wait,
            do_byte_sweep=not args.no_byte_sweep,
            device_id=args.device_id, serial=args.serial,
        )
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
