#!/usr/bin/env python3
"""
Read-only recon of the router over SSH.

Goal: verify that the iptables DNAT+MASQUERADE plan for redirecting
192.168.0.11's DNS to 192.168.0.22:53 will work safely on THIS router.

Strict rules (from operator):
  * read-only commands only
  * print every command + reason before running
  * stop and ask on anything unexpected

Commands executed (all read-only):
  uname -a                          # what kernel/firmware
  cat /etc/os-release || ...        # distro / Keenetic / OpenWrt / ...
  id                                # who we run as
  ip -o addr                        # interface IPs (find LAN bridge)
  ip route                          # default route, LAN scope
  brctl show 2>/dev/null || ...     # bridge members
  cat /proc/net/arp                 # is the Capsula visible?
  arp -an 2>/dev/null               # alternate ARP listing
  iptables --version                # capabilities
  iptables -t nat -S                # full nat table snapshot
  iptables -t nat -L PREROUTING -n -v
  iptables -t nat -L POSTROUTING -n -v
  iptables -t nat -L OUTPUT -n -v
  iptables -t filter -S | head -50  # peek at filter rules (truncated)
  conntrack --version 2>/dev/null   # is conntrack tool present?
  ps w | head -50                   # snapshot of processes
  mount                             # mount table
  cat /proc/version
"""
import sys
import time

import paramiko

ROUTER_HOST = "192.168.0.1"
ROUTER_USER = "superadmin"
ROUTER_PASS = "8WHoDt3yCQR98BRx"

# Each entry: (label, command, why)
COMMANDS = [
    ("uname",           "uname -a",                              "kernel/firmware identity"),
    ("os_release",      "cat /etc/os-release 2>/dev/null || cat /etc/openwrt_release 2>/dev/null || cat /etc/issue 2>/dev/null",
                                                                  "distro / Keenetic / OpenWrt"),
    ("whoami",          "id",                                    "confirm we're root (uid 0) for iptables"),
    ("interfaces",      "ip -o addr show 2>/dev/null || ifconfig",
                                                                  "find which iface has 192.168.0.1 (LAN bridge)"),
    ("routes",          "ip route 2>/dev/null || route -n",      "verify capsula 192.168.0.11 is on directly attached LAN"),
    ("bridges",         "brctl show 2>/dev/null || true",        "see br2 / br-lan membership"),
    ("arp",             "cat /proc/net/arp 2>/dev/null || arp -an",
                                                                  "is 192.168.0.11 visible? what MAC?"),
    ("iptables_ver",    "iptables --version 2>&1 || true",        "module / version check"),
    ("nat_S",           "iptables -t nat -S 2>&1",                "full nat ruleset before changes (audit baseline)"),
    ("nat_PREROUTING",  "iptables -t nat -L PREROUTING -n -v 2>&1","existing PREROUTING in the nat table"),
    ("nat_POSTROUTING", "iptables -t nat -L POSTROUTING -n -v 2>&1","existing POSTROUTING in the nat table"),
    ("nat_OUTPUT",      "iptables -t nat -L OUTPUT -n -v 2>&1",   "existing OUTPUT in the nat table"),
    ("filter_S_head",   "iptables -t filter -S 2>&1 | head -60",  "peek at filter rules so we don't surprise FORWARD"),
    ("conntrack_ver",   "conntrack --version 2>&1 || echo 'conntrack-tool: NOT INSTALLED'",
                                                                  "is conntrack-tools available for cache flush?"),
    ("ps",              "ps w 2>/dev/null | head -80 || ps -ef | head -80",
                                                                  "snapshot of running processes"),
    ("mount",           "mount",                                  "mount table snapshot"),
    ("listening",       "netstat -tunlp 2>/dev/null | head -40 || netstat -an 2>/dev/null | head -40",
                                                                  "what is listening on the router (any DNS forwarder?)"),
    ("kernel",          "cat /proc/version",                      "kernel version"),
]


def main():
    print("=" * 70)
    print(f"Router recon -> {ROUTER_USER}@{ROUTER_HOST}")
    print("READ-ONLY. No state changes. No reboots, no kills, no edits.")
    print("=" * 70)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"\n[*] connecting to {ROUTER_HOST} (legacy algorithms enabled)...")
    try:
        client.connect(
            hostname=ROUTER_HOST,
            username=ROUTER_USER,
            password=ROUTER_PASS,
            timeout=15,
            allow_agent=False,
            look_for_keys=False,
            # accept old kex/host-key/hmac so it works on stock router SSH
            disabled_algorithms={
                "pubkeys": [],
                "kex":     [],
                "keys":    [],
                "ciphers": [],
                "macs":    [],
            },
        )
    except Exception as e:
        print(f"[!] SSH connect failed: {type(e).__name__}: {e}")
        sys.exit(2)
    print("[*] connected.\n")

    results = {}
    for label, cmd, reason in COMMANDS:
        print("-" * 70)
        print(f"[{label}]  reason: {reason}")
        print(f"  $ {cmd}")
        try:
            stdin, stdout, stderr = client.exec_command(cmd, timeout=20)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            rc = stdout.channel.recv_exit_status()
        except Exception as e:
            print(f"  ! exec error: {type(e).__name__}: {e}")
            results[label] = {"error": str(e)}
            continue
        results[label] = {"rc": rc, "stdout": out, "stderr": err}
        if out:
            for line in out.splitlines()[:80]:
                print(f"    {line}")
            if len(out.splitlines()) > 80:
                print(f"    ... [+{len(out.splitlines()) - 80} more lines]")
        if err.strip():
            for line in err.splitlines()[:20]:
                print(f"    [stderr] {line}")
        if rc != 0:
            print(f"    (rc={rc})")
        time.sleep(0.1)

    client.close()

    print("\n" + "=" * 70)
    print("Recon done. NO CHANGES were made.")
    print("=" * 70)


if __name__ == "__main__":
    main()
