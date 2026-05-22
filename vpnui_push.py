#!/usr/bin/env python3
"""
Push vpnui files to the router without relying on sftp-server or any
base64/xxd/ssh-subsystem that the firmware might lack.

Pattern is borrowed from router_restore_panel.ps1 which is already
proven to work on this device:
  - every shell command is a fresh SSH connection (dropbear drops the
    session after each exec),
  - RSA-SHA2 pubkey algs are disabled so paramiko can auth against the
    old dropbear,
  - up to 4 retries per command with a short backoff,
  - output is captured via a polling loop instead of recv_exit_status.

The actual file upload is a single shell command per file, of the form:

    mkdir -p 'USB_DIR' &&
    /var/tmp/vpnui/bin/busybox-mips printf '%b' '\\xNN\\xNN...' > 'USB_TMP' &&
    mv 'USB_TMP' 'USB_DST' &&
    mkdir -p 'RAM_DIR' &&
    cp -a 'USB_DST' 'RAM_DST' &&
    chmod +x 'RAM_DST'      # only for *.cgi / *.sh

This way the whole per-file write is atomic in one SSH session. No
services are killed, no reboot, no file deletion outside of the one
target.

Usage:
    python vpnui_push.py                    # default: the 4 CGI files
    python vpnui_push.py --all              # everything under vpnui/site/
    python vpnui_push.py cgi-bin/rules.cgi  # specific files
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import paramiko

ROUTER_HOST = "192.168.0.1"
ROUTER_USER = "superadmin"
ROUTER_PASS = "8WHoDt3yCQR98BRx"

USB_ROOT = "/var/usbmnt/sda1/vpnui/www"
RAM_ROOT = "/var/tmp/vpnui/www"
BB_REMOTE = "/var/tmp/vpnui/bin/busybox-mips"

LOCAL_SITE = Path(__file__).parent / "vpnui" / "site"

DEFAULT_FILES = [
    "cgi-bin/rules.cgi",      # grep -Fv fix (was deleting multiple rules)
    "cgi-bin/selective.cgi",  # new: selective tunnel manager
    "cgi-bin/devices.cgi",    # new: device rename / hostname
    "cgi-bin/info.cgi",       # extended: hostname + name override
]


# ---------------------------------------------------------------------------
# SSH helper: one exec per connection, retries, pattern from
# router_restore_panel.ps1.
# ---------------------------------------------------------------------------
_last_run = 0.0
_MIN_GAP = 0.35  # seconds dropbear needs between back-to-back sessions


def run_ssh(cmd: str, timeout: int = 30, tries: int = 6) -> str:
    global _last_run
    last_exc: Exception | None = None
    for attempt in range(tries):
        # back-off both on retry and just between successful calls.
        gap = _MIN_GAP + (attempt * 0.8 if attempt else 0.0)
        wait = gap - (time.time() - _last_run)
        if wait > 0:
            time.sleep(wait)

        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            c.connect(
                ROUTER_HOST, 22,
                username=ROUTER_USER, password=ROUTER_PASS,
                timeout=15, banner_timeout=15, auth_timeout=15,
                look_for_keys=False, allow_agent=False,
                disabled_algorithms={
                    "pubkeys": ["rsa-sha2-256", "rsa-sha2-512"],
                },
            )
            _, stdout, stderr = c.exec_command(cmd + " 2>&1", timeout=timeout)
            ch = stdout.channel
            buf = b""
            deadline = time.time() + timeout
            while time.time() < deadline:
                if ch.recv_ready():
                    buf += ch.recv(4096)
                if ch.exit_status_ready():
                    while ch.recv_ready():
                        buf += ch.recv(4096)
                    break
                time.sleep(0.1)
            try:
                ch.close()
            except Exception:
                pass
            _last_run = time.time()
            return buf.decode("utf-8", errors="replace")
        except Exception as e:
            last_exc = e
            _last_run = time.time()
            time.sleep(1.5)
        finally:
            try:
                c.close()
            except Exception:
                pass
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# File upload: hex-escape + printf '%b' in one big command.
# ---------------------------------------------------------------------------
def _shell_q(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _hex_escape(b: bytes) -> str:
    return "".join(f"\\x{c:02x}" for c in b)


# Dropbear on this firmware silently drops sessions where the SSH
# exec-request payload goes above ~1 KB. We keep each chunk tiny so the
# whole printf command stays under ~900 shell bytes.
#   200 raw bytes -> 800 bytes of '\xNN' escape + ~60 bytes wrapper
CHUNK_BYTES = 200


def _ok(out: str) -> None:
    if "__OK__" not in out:
        raise RuntimeError(f"remote failed:\n{out.strip()[-600:]}")


def push_file(rel: str, *, usb_only: bool, ram_only: bool) -> None:
    local = LOCAL_SITE / rel
    if not local.is_file():
        raise FileNotFoundError(str(local))
    data = local.read_bytes()
    make_exec = rel.endswith(".cgi") or rel.endswith(".sh")
    n_chunks = max(1, (len(data) + CHUNK_BYTES - 1) // CHUNK_BYTES)
    print(f"  PUT  {rel}  ({len(data)} bytes, {n_chunks} chunk(s), "
          f"exec={make_exec})")

    # Stage the content on the USB stick (or RAM if usb is skipped).
    # We write chunk-by-chunk to <dst>.tmp via >> to avoid the 4 KB
    # dropbear exec-request limit.
    if ram_only:
        stage_dst = f"{RAM_ROOT}/{rel}"
    else:
        stage_dst = f"{USB_ROOT}/{rel}"
    stage_tmp = stage_dst + ".tmp"
    stage_dir = os.path.dirname(stage_dst)

    # Make sure the staging dir exists.
    out = run_ssh(f"mkdir -p {_shell_q(stage_dir)}; echo __OK__")
    _ok(out)

    # Write each chunk in its own SSH session.
    # First chunk uses '>' (truncates/creates tmp), rest use '>>'. This
    # avoids the ':>file' / 'true>file' quirks we saw on this ash build
    # and keeps every exec request well under 4 KB.
    for i in range(n_chunks):
        chunk = data[i * CHUNK_BYTES : (i + 1) * CHUNK_BYTES]
        esc = _hex_escape(chunk)
        redir = ">" if i == 0 else ">>"
        cmd = (
            f"{BB_REMOTE} printf '%b' '{esc}' {redir} {_shell_q(stage_tmp)}"
            f"; echo __OK__"
        )
        out = run_ssh(cmd, timeout=30)
        _ok(out)
        if (i + 1) % 8 == 0 or i + 1 == n_chunks:
            print(f"    chunk {i + 1}/{n_chunks}")

    # Atomic rename of tmp -> final staging dst.
    out = run_ssh(
        f"mv {_shell_q(stage_tmp)} {_shell_q(stage_dst)}; echo __OK__"
    )
    _ok(out)

    # Mirror USB -> RAM if needed, chmod +x for CGI / sh.
    if not usb_only and not ram_only:
        ram_dst = f"{RAM_ROOT}/{rel}"
        ram_dir = os.path.dirname(ram_dst)
        cmd = (
            f"mkdir -p {_shell_q(ram_dir)}; "
            f"cp -a {_shell_q(stage_dst)} {_shell_q(ram_dst)}; "
        )
        if make_exec:
            cmd += f"chmod +x {_shell_q(ram_dst)}; "
        cmd += "echo __OK__"
        out = run_ssh(cmd)
        _ok(out)
    elif make_exec:
        out = run_ssh(f"chmod +x {_shell_q(stage_dst)}; echo __OK__")
        _ok(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def collect_targets(argv_files: list[str], all_flag: bool) -> list[str]:
    if all_flag:
        files: list[str] = []
        for p in LOCAL_SITE.rglob("*"):
            if p.is_file():
                files.append(p.relative_to(LOCAL_SITE).as_posix())
        return sorted(files)
    if argv_files:
        return argv_files
    return DEFAULT_FILES


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*",
                    help="paths relative to vpnui/site/ (default: built-in list)")
    ap.add_argument("--all", action="store_true",
                    help="push every file under vpnui/site/")
    ap.add_argument("--usb-only", action="store_true",
                    help="write only to the USB stick (persistent, lost hot apply)")
    ap.add_argument("--ram-only", action="store_true",
                    help="write only to RAM (non-persistent, lost on reboot)")
    args = ap.parse_args()

    if args.usb_only and args.ram_only:
        print("[!] --usb-only and --ram-only are mutually exclusive")
        return 2

    targets = collect_targets(args.files, args.all)
    missing = [t for t in targets if not (LOCAL_SITE / t).is_file()]
    if missing:
        print("[!] missing local files, aborting:")
        for m in missing:
            print(f"    {LOCAL_SITE / m}")
        return 2

    print("=" * 70)
    print("vpnui push")
    print(f"  local root : {LOCAL_SITE}")
    print(f"  router     : {ROUTER_USER}@{ROUTER_HOST}")
    print(f"  usb root   : {USB_ROOT}  {'(skipped)' if args.ram_only else ''}")
    print(f"  ram root   : {RAM_ROOT}  {'(skipped)' if args.usb_only else ''}")
    print("-" * 70)
    print("files:")
    for t in targets:
        print(f"  {t}")
    print("=" * 70)

    for rel in targets:
        try:
            push_file(rel, usb_only=args.usb_only, ram_only=args.ram_only)
        except Exception as e:
            print(f"[!] {rel}: {type(e).__name__}: {e}")
            return 2

    # Verify visible sizes in RAM (if we touched RAM).
    if not args.usb_only:
        print("\n[*] verify RAM copies:")
        ls_paths = " ".join(_shell_q(f"{RAM_ROOT}/{t}") for t in targets)
        out = run_ssh(f"ls -l {ls_paths}")
        for line in out.strip().splitlines():
            print(f"    {line}")

    print("\n[*] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
