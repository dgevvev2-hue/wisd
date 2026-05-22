#!/usr/bin/env python3
"""
Quick health-check of the DNS-redirect: read-only, no changes.

Tells us:
  * are the 4 iptables rules still in place
  * have ANY packets matched them (pkts > 0 means Capsula has been doing
    DNS to router, and router has been DNATing it to PC)
  * is 192.168.0.22:53 reachable from the router (router can reach PC?)
  * what does the Capsula's last-seen ARP look like
"""
import sys
import paramiko

ROUTER_HOST = "192.168.0.1"
ROUTER_USER = "superadmin"
ROUTER_PASS = "8WHoDt3yCQR98BRx"

CMDS = [
    ("rules_PREROUTING",
     "iptables -t nat -L PREROUTING -n -v | head -8",
     "see DNAT rules and their pkts/bytes counters"),
    ("rules_POSTROUTING",
     "iptables -t nat -L POSTROUTING -n -v | head -8",
     "see MASQUERADE rules and their pkts/bytes counters"),
    ("rules_S",
     "iptables -t nat -S PREROUTING | head -5; iptables -t nat -S POSTROUTING | head -5",
     "snapshot to compare with what we applied"),
    ("conntrack_dns",
     "cat /proc/net/nf_conntrack 2>/dev/null | grep -E '192\\.168\\.0\\.11.*dport=53' | head -10",
     "live conntrack entries for capsule's DNS"),
    ("arp_capsula",
     "cat /proc/net/arp | grep -E '192\\.168\\.0\\.11\\b' || echo 'capsula not in ARP'",
     "is capsule even reachable from router right now"),
    ("ping_pc",
     "ping -c 2 -W 1 192.168.0.22 2>&1 | tail -5",
     "can router reach the PC at all"),
    ("dns_test_to_pc",
     "nslookup ya.ru 192.168.0.22 2>&1 | head -10 || echo 'nslookup not present'",
     "can router resolve via PC's logger right now (PC must be running logger as admin)"),
    ("listen_local",
     "netstat -tunl 2>/dev/null | head -30",
     "what is router itself listening on"),
]


def main():
    print("=" * 70)
    print("DNS-redirect health-check (read-only)")
    print("=" * 70)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(hostname=ROUTER_HOST, username=ROUTER_USER, password=ROUTER_PASS,
                  timeout=15, allow_agent=False, look_for_keys=False)
    except Exception as e:
        print(f"[!] SSH failed: {e}")
        sys.exit(2)

    for label, cmd, why in CMDS:
        print("-" * 70)
        print(f"[{label}]  {why}")
        print(f"  $ {cmd}")
        stdin, stdout, stderr = c.exec_command(cmd, timeout=15)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        for line in out.splitlines()[:30]:
            print(f"    {line}")
        if err.strip():
            for line in err.splitlines()[:10]:
                print(f"    [stderr] {line}")
        if rc != 0:
            print(f"    (rc={rc})")
    c.close()
    print("=" * 70)


if __name__ == "__main__":
    main()
