#!/usr/bin/env python3
"""
Capsula Mini HTTP probe.

Two surfaces:
  1) :8081  Spotify Connect ZeroConf API  (Server: eSDK)
            GET  <CPath>?action=getInfo&version=2.10.0
            Try a handful of common CPaths until one returns JSON
            with "spotifyError" / "deviceID" / "publicKey".
  2) :80    Vendor mini-HTTP where URL path == command name.
            /info already works. Brute a curated command list and log
            anything that is NOT "404 command not found".

Pure stdlib. No mutation: only GET + OPTIONS, never POST.
Output is written to ./capsula_probe_results.json.

Usage:
    python capsula_probe.py [--host 192.168.0.11]
                            [--port80-only] [--port8081-only]
                            [--threads 8]
"""

import argparse
import concurrent.futures as futures
import http.client
import json
import os
import socket
import ssl
import sys
import time
from typing import Optional
from urllib.parse import urlencode

DEFAULT_HOST = "192.168.0.11"

# Spotify ZeroConf: every shipped device uses some CPath. We probe the
# usual suspects; whichever one returns JSON with spotifyError wins.
SPOTIFY_CPATHS = [
    "/zc",
    "/zeroconf",
    "/spotify_info",
    "/spotify",
    "/spotifyzc",
    "/eSDK",
    "/spotify-connect",
    "/connect",
    "/",
    "/api/zc",
    "/api/spotify",
]

# :80 command wordlist for VK Капсула Мини. Tiered so we don't hammer
# the fragile single-threaded vendor server.
#
# tier 1: high-value commands derived from the /info pattern (single-word
#         leaf paths in snake_case, JSON output expected).
# tier 2: variations + common embedded vocab.
# tier 3: paths that often hide command-injection or path-traversal
#         (interesting for the SSH-access goal).
PORT80_TIER1 = [
    # known
    "/info",
    # info-style siblings - most likely to exist alongside /info
    "/status", "/state", "/version", "/health", "/about",
    "/sysinfo", "/devinfo", "/dev_info", "/device_info",
    "/info_full", "/full_info", "/uptime", "/stats",
    # network state
    "/wifi", "/wifi_info", "/wifi_status", "/network", "/net_info",
    "/ip_info", "/ifconfig",
    # audio/playback state
    "/audio", "/audio_info", "/playback", "/player", "/volume",
    "/track", "/now_playing", "/state_audio",
    # bluetooth
    "/bt", "/bt_info", "/bt_status", "/bluetooth",
    # update / OTA - high value
    "/update", "/ota", "/firmware", "/fw_info", "/check_update",
    # logs / debug - very high value if exposed
    "/log", "/logs", "/debug", "/dmesg", "/syslog", "/journal",
    # config
    "/config", "/settings", "/cfg",
]

PORT80_TIER2 = [
    # voice / Marusya
    "/voice", "/asr", "/tts", "/marusya", "/marusia", "/assistant",
    "/wakeword", "/wake_word", "/mic", "/skill", "/skills",
    # API roots / versioned
    "/api", "/api/info", "/api/v1/info", "/v1/info",
    "/rpc", "/jsonrpc", "/eapi",
    # display / LED
    "/led", "/leds", "/display", "/screen", "/clock", "/time", "/light",
    # control
    "/play", "/pause", "/stop", "/next", "/prev", "/mute", "/unmute",
    "/volume_up", "/volume_down",
    # smart home / iot
    "/iot", "/devices", "/smart_home", "/zigbee", "/discovery",
    # auth / pairing
    "/auth", "/pair", "/pairing", "/token", "/cert", "/account", "/user",
    # service control
    "/reboot", "/restart", "/shutdown", "/poweroff",
    "/factory_reset", "/factory-reset", "/reset",
    # health / probes
    "/ping", "/healthz", "/readyz", "/livez",
    # eSDK-adjacent on :80
    "/zc", "/zeroconf", "/spotify", "/spotify_info",
    # discovery surfaces
    "/description.xml", "/setup.xml",
    "/.well-known/spotify-connect",
]

PORT80_TIER3 = [
    # endpoints that often hide command injection / file read
    "/cmd", "/command", "/exec", "/shell", "/run",
    "/file", "/files", "/fs", "/storage", "/get_file", "/read",
    "/download", "/upload",
    # diagnostics that may shell out
    "/diag", "/diagnostics", "/ping_test", "/traceroute", "/nslookup",
    "/test_net", "/speedtest",
    # config that may write
    "/wifi_setup", "/wifi_connect", "/connect_wifi", "/setup",
    "/set_wifi", "/save_config", "/apply",
    # sshd-related (sometimes there's a flag)
    "/enable_ssh", "/ssh", "/dropbear", "/telnet", "/dev_mode",
    "/developer", "/service_mode",
    # path-traversal probes
    "/info?path=/etc/passwd",
    "/info?file=/etc/passwd",
    "/log?file=../../etc/passwd",
    "/log?path=../../../../etc/passwd",
]


def http_request(host, port, method, path,
                 timeout=3.0, body=None,
                 headers=None, use_https=False):
    # type: (str, int, str, str, float, Optional[bytes], Optional[dict], bool) -> Optional[dict]
    """Single HTTP request with no kept connection. Returns dict or None."""
    headers = dict(headers or {})
    headers.setdefault("User-Agent", "capsula-probe/1.0")
    headers.setdefault("Accept", "*/*")
    try:
        if use_https:
            ctx = ssl._create_unverified_context()
            conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read(65536)
        result = {
            "method": method,
            "path": path,
            "status": resp.status,
            "reason": resp.reason,
            "headers": dict(resp.getheaders()),
            "body_len": len(raw),
            "body_preview": _preview(raw),
        }
        conn.close()
        return result
    except (socket.timeout, TimeoutError):
        return {"method": method, "path": path, "error": "timeout"}
    except (ConnectionRefusedError, ConnectionResetError) as e:
        return {"method": method, "path": path, "error": f"{type(e).__name__}: {e}"}
    except OSError as e:
        return {"method": method, "path": path, "error": f"OSError: {e}"}
    except Exception as e:
        return {"method": method, "path": path, "error": f"{type(e).__name__}: {e}"}


def _preview(raw, limit=600):
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"<{len(raw)} bytes binary; hex={raw[:64].hex()}>"
    if len(text) > limit:
        text = text[:limit] + f"... [+{len(raw) - limit} bytes]"
    return text


# ---------- Spotify ZeroConf probe (:8081) ----------

def probe_spotify(host):
    print(f"\n=== Spotify ZeroConf on {host}:8081 ===")
    findings = []
    winner = None
    qs = urlencode({"action": "getInfo", "version": "2.10.0"})
    for cpath in SPOTIFY_CPATHS:
        path = f"{cpath}?{qs}" if cpath != "/" else f"/?{qs}"
        r = http_request(host, 8081, "GET", path, timeout=3.0)
        if not r or r.get("error"):
            print(f"  GET 8081 {path:30s}  ERR: {r.get('error') if r else 'no response'}")
            continue
        status = r["status"]
        body = r["body_preview"]
        is_json_zc = (
            status == 200
            and ("spotifyError" in body or "deviceID" in body or "publicKey" in body)
        )
        marker = "  *** ZEROCONF ***" if is_json_zc else ""
        print(f"  GET 8081 {path:30s}  -> {status} {r['reason']} ({r['body_len']}B){marker}")
        findings.append(r)
        if is_json_zc and winner is None:
            winner = {"cpath": cpath, "raw": body}
            try:
                winner["parsed"] = json.loads(
                    body if not body.endswith("]") else body  # body_preview may be truncated
                )
            except Exception:
                pass

    # OPTIONS on the winning CPath (or on / if none) gives Allow: header
    opath = (winner["cpath"] if winner else "/")
    r_opts = http_request(host, 8081, "OPTIONS", opath, timeout=3.0)
    print(f"  OPTIONS 8081 {opath:25s}  -> {r_opts.get('status')} "
          f"{r_opts.get('reason') or r_opts.get('error')}  "
          f"Allow={r_opts.get('headers', {}).get('Allow') if isinstance(r_opts, dict) else None}")
    findings.append(r_opts)

    return {"winner": winner, "all": findings}


# ---------- Vendor :80 brute ----------

def looks_like_404_command(r):
    """Server returns 404 with body 'command not found' for unknown URLs."""
    if not r or r.get("error"):
        return False
    if r.get("status") != 404:
        return False
    body = (r.get("body_preview") or "").lower()
    return "command not found" in body


def _info_alive(host, timeout=2.5):
    r = http_request(host, 80, "GET", "/info", timeout=timeout)
    return bool(r and r.get("status") == 200)


def probe_port80(host, tier, delay, health_every, max_consecutive_timeouts,
                 cooldown):
    paths = []
    paths += PORT80_TIER1
    if tier >= 2:
        paths += PORT80_TIER2
    if tier >= 3:
        paths += PORT80_TIER3
    # de-dup, keep order
    seen = set()
    paths = [p for p in paths if not (p in seen or seen.add(p))]

    print(f"\n=== Vendor HTTP on {host}:80 sequential brute ===")
    print(f"    {len(paths)} paths, delay {delay}s, health-check every {health_every}")

    if not _info_alive(host):
        print("  [!] /info is not responsive at start - server already down? aborting")
        return {"all": [], "aborted": True, "total_tried": 0}

    all_responses = []
    interesting = []
    boring_404 = 0
    consecutive_timeouts = 0
    aborted = False

    for idx, path in enumerate(paths, 1):
        # health check
        if health_every and idx > 1 and (idx - 1) % health_every == 0:
            if not _info_alive(host):
                print(f"  [!] /info stopped responding at #{idx} - cooling down {cooldown}s")
                time.sleep(cooldown)
                if not _info_alive(host):
                    print("  [!] still down - aborting brute")
                    aborted = True
                    break
                consecutive_timeouts = 0

        r = http_request(host, 80, "GET", path, timeout=3.0)
        all_responses.append(r)

        if r is None:
            print(f"  [{idx:3d}/{len(paths)}] GET {path:35s}  no response")
            consecutive_timeouts += 1
        elif r.get("error"):
            err = r["error"]
            print(f"  [{idx:3d}/{len(paths)}] GET {path:35s}  ERR: {err}")
            if "timeout" in err.lower():
                consecutive_timeouts += 1
            else:
                consecutive_timeouts = 0
        else:
            consecutive_timeouts = 0
            status = r["status"]
            blen = r["body_len"]
            ctype = r["headers"].get("Content-Type", "?")
            if looks_like_404_command(r):
                boring_404 += 1
                # still print briefly so we know it was reachable
                print(f"  [{idx:3d}/{len(paths)}] GET {path:35s}  -> 404 cmd-not-found")
            else:
                print(f"  [{idx:3d}/{len(paths)}] GET {path:35s}  -> {status} {r['reason'] or '':12s} {blen:5d}B  {ctype}")
                preview = (r["body_preview"] or "").replace("\n", " ")[:160]
                if preview:
                    print(f"            | {preview}")
                interesting.append(r)

        if consecutive_timeouts >= max_consecutive_timeouts:
            print(f"  [!] {consecutive_timeouts} timeouts in a row - cooling down {cooldown}s")
            time.sleep(cooldown)
            if not _info_alive(host):
                print("  [!] /info still dead - aborting brute")
                aborted = True
                break
            consecutive_timeouts = 0

        time.sleep(delay)

    return {
        "all": all_responses,
        "interesting": interesting,
        "boring_404": boring_404,
        "total_tried": len(paths),
        "aborted": aborted,
        "tier": tier,
    }


def _save(out_path, data):
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        print(f"  [saved] {out_path}  ({os.path.getsize(out_path)} bytes)")
    except Exception as e:
        print(f"  [save error] {e}", file=sys.stderr)


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.join(script_dir, "capsula_probe_results.json")

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port80-only", action="store_true")
    ap.add_argument("--port8081-only", action="store_true")
    ap.add_argument("--tier", type=int, default=1, choices=[1, 2, 3],
                    help="size of :80 wordlist (1=safe, 2=extended, 3=injection-probes)")
    ap.add_argument("--delay", type=float, default=0.5,
                    help="seconds to sleep between :80 requests")
    ap.add_argument("--health-every", type=int, default=10,
                    help="check /info every N requests; 0=off")
    ap.add_argument("--max-timeouts", type=int, default=4,
                    help="abort cooldown after this many consecutive timeouts")
    ap.add_argument("--cooldown", type=float, default=10.0,
                    help="seconds to wait after server appears stuck")
    ap.add_argument("--slow", action="store_true",
                    help="gentle preset: delay 2.5s, health every 5, cooldown 20s")
    ap.add_argument("--out", default=default_out)
    args = ap.parse_args()

    if args.slow:
        args.delay = max(args.delay, 2.5)
        args.health_every = min(args.health_every, 5) if args.health_every else 5
        args.max_timeouts = min(args.max_timeouts, 3)
        args.cooldown = max(args.cooldown, 20.0)
        print(f"[slow] delay={args.delay}s  health_every={args.health_every}  "
              f"max_timeouts={args.max_timeouts}  cooldown={args.cooldown}s")

    out_path = os.path.abspath(args.out)
    print(f"Capsula Mini HTTP probe -> {args.host}")
    print(f"Python: {sys.version.split()[0]}  cwd={os.getcwd()}")
    print(f"Will write results to: {out_path}")

    started = time.time()
    out = {"host": args.host, "started_at": started, "python": sys.version}

    try:
        if not args.port80_only:
            out["spotify"] = probe_spotify(args.host)
            _save(out_path, out)  # checkpoint after phase 1
        if not args.port8081_only:
            out["port80"] = probe_port80(
                args.host,
                tier=args.tier,
                delay=args.delay,
                health_every=args.health_every,
                max_consecutive_timeouts=args.max_timeouts,
                cooldown=args.cooldown,
            )
    except KeyboardInterrupt:
        print("\n[interrupted] saving partial results...")
        out["interrupted"] = True
    except Exception as e:
        print(f"\n[error] {type(e).__name__}: {e}")
        out["error"] = f"{type(e).__name__}: {e}"
    finally:
        out["elapsed_sec"] = round(time.time() - started, 2)
        _save(out_path, out)

    print(f"\nDone in {out['elapsed_sec']}s. Full results -> {out_path}")
    if out.get("spotify", {}).get("winner"):
        w = out["spotify"]["winner"]
        print(f"\n*** Spotify ZeroConf CPath: {w['cpath']}")
        if "parsed" in w:
            keys = ("deviceID", "remoteName", "brandDisplayName",
                    "modelDisplayName", "libraryVersion", "deviceType",
                    "publicKey")
            for k in keys:
                v = w["parsed"].get(k)
                if v is not None:
                    pv = (str(v)[:80] + "...") if len(str(v)) > 80 else v
                    print(f"      {k}: {pv}")

    if out.get("port80", {}).get("interesting"):
        print(f"\n*** :80 non-404 hits ({len(out['port80']['interesting'])}):")
        for r in out["port80"]["interesting"]:
            print(f"      {r['status']:3d}  {r['path']}")


if __name__ == "__main__":
    sys.exit(main())
