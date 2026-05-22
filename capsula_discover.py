#!/usr/bin/env python3
"""
Capsula Mini local-network discovery: mDNS + SSDP.

Pure stdlib. Run on the SAME LAN as the device (e.g. 192.168.0.0/24).
Goal: catch what the device advertises (service types, ports, TXT records)
without poking its HTTP API. Anything coming from 192.168.0.11 is the prize.

Usage:
    python capsula_discover.py
    python capsula_discover.py --mdns-timeout 12 --ssdp-timeout 8
"""
import argparse
import socket
import struct
import sys
import time

MDNS_ADDR = ("224.0.0.251", 5353)
SSDP_ADDR = ("239.255.255.250", 1900)

# Service types worth asking about. The first one is a meta-query that
# returns *every* service type a responder publishes.
MDNS_QUERIES = [
    "_services._dns-sd._udp.local",
    # Russian smart-speaker ecosystems
    "_yandexio._tcp.local",
    "_sberdevices._tcp.local",
    "_salute._tcp.local",
    "_esdk._tcp.local",
    "_capsula._tcp.local",
    # generic media / cast
    "_googlecast._tcp.local",
    "_airplay._tcp.local",
    "_raop._tcp.local",
    "_spotify-connect._tcp.local",
    "_dlna._tcp.local",
    # generic / debug surfaces
    "_http._tcp.local",
    "_https._tcp.local",
    "_workstation._tcp.local",
    "_smb._tcp.local",
    "_ssh._tcp.local",
    "_sftp-ssh._tcp.local",
    "_telnet._tcp.local",
    "_adb._tcp.local",
    # smart-home
    "_hap._tcp.local",
    "_matter._tcp.local",
    "_matterc._udp.local",
    "_matterd._udp.local",
    "_meshcop._udp.local",
    "_alexa._tcp.local",
    "_amzn-wplay._tcp.local",
    "_companion-link._tcp.local",
]

SSDP_STS = [
    "ssdp:all",
    "upnp:rootdevice",
    "urn:dial-multiscreen-org:service:dial:1",
    "urn:schemas-upnp-org:device:MediaRenderer:1",
    "urn:schemas-upnp-org:device:MediaServer:1",
    "urn:schemas-upnp-org:device:Basic:1",
    "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
    "urn:yandex-com:device:Capsule:1",
    "urn:sberdevices-com:device:Capsule:1",
    "urn:sberdevices-com:device:Speaker:1",
]


# ---------- DNS / mDNS ----------

def build_mdns_query(name: str) -> bytes:
    header = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)
    qname = b""
    for label in name.split("."):
        if not label:
            continue
        b = label.encode("ascii")
        qname += bytes([len(b)]) + b
    qname += b"\x00"
    # QTYPE = PTR (12), QCLASS = IN (1) with QU bit set (0x8000) so
    # responders unicast the answer back to our ephemeral source port.
    question = qname + struct.pack("!HH", 12, 0x8001)
    return header + question


def parse_dns_name(buf: bytes, offset: int):
    parts = []
    jumped = False
    return_offset = offset
    safety = 0
    while True:
        safety += 1
        if safety > 128 or offset >= len(buf):
            break
        ln = buf[offset]
        if ln == 0:
            offset += 1
            break
        if ln & 0xC0 == 0xC0:
            if offset + 1 >= len(buf):
                break
            ptr = ((ln & 0x3F) << 8) | buf[offset + 1]
            if not jumped:
                return_offset = offset + 2
            jumped = True
            offset = ptr
            continue
        offset += 1
        parts.append(buf[offset:offset + ln].decode("ascii", errors="replace"))
        offset += ln
    if not jumped:
        return_offset = offset
    return ".".join(parts), return_offset


def parse_dns_response(data: bytes):
    records = []
    if len(data) < 12:
        return records
    qd, an, ns, ar = struct.unpack("!HHHH", data[4:12])
    offset = 12
    for _ in range(qd):
        _, offset = parse_dns_name(data, offset)
        offset += 4
    for _ in range(an + ns + ar):
        if offset + 10 > len(data):
            break
        name, offset = parse_dns_name(data, offset)
        if offset + 10 > len(data):
            break
        rtype, _rclass, _ttl, rdlen = struct.unpack("!HHIH", data[offset:offset + 10])
        offset += 10
        rdata = data[offset:offset + rdlen]
        if rtype == 12:  # PTR
            ptrname, _ = parse_dns_name(data, offset)
            records.append(("PTR", name, ptrname))
        elif rtype == 1 and rdlen == 4:  # A
            ip = ".".join(str(b) for b in rdata)
            records.append(("A", name, ip))
        elif rtype == 28 and rdlen == 16:  # AAAA
            try:
                ip6 = socket.inet_ntop(socket.AF_INET6, rdata)
            except OSError:
                ip6 = rdata.hex()
            records.append(("AAAA", name, ip6))
        elif rtype == 33 and rdlen >= 7:  # SRV
            _prio, _w, port = struct.unpack("!HHH", rdata[:6])
            tgt, _ = parse_dns_name(data, offset + 6)
            records.append(("SRV", name, f"{tgt}:{port}"))
        elif rtype == 16:  # TXT
            txts, i = [], 0
            while i < len(rdata):
                ln = rdata[i]; i += 1
                txts.append(rdata[i:i + ln].decode("utf-8", errors="replace"))
                i += ln
            records.append(("TXT", name, " | ".join(txts)))
        else:
            records.append((f"TYPE{rtype}", name, rdata.hex()))
        offset += rdlen
    return records


def mdns_probe(timeout: float):
    print(f"\n=== mDNS probe ({len(MDNS_QUERIES)} service types, ~{timeout:.0f}s) ===")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    s.settimeout(0.4)
    s.bind(("", 0))
    sent = 0
    for q in MDNS_QUERIES:
        try:
            s.sendto(build_mdns_query(q), MDNS_ADDR)
            sent += 1
        except OSError as e:
            print(f"  send-fail {q}: {e}")
    print(f"  sent {sent} queries from local port {s.getsockname()[1]}")
    deadline = time.time() + timeout
    by_host = {}
    while time.time() < deadline:
        try:
            data, addr = s.recvfrom(8192)
        except socket.timeout:
            continue
        recs = parse_dns_response(data)
        if not recs:
            continue
        by_host.setdefault(addr[0], []).append(recs)
    s.close()

    if not by_host:
        print("  (no mDNS replies — Windows Firewall may be blocking inbound UDP, "
              "or there is no responder on this segment)")
        return

    for host in sorted(by_host):
        print(f"\n[mDNS] {host}  ({len(by_host[host])} packet(s))")
        seen_lines = set()
        for pkt in by_host[host]:
            for t, n, v in pkt:
                line = f"   {t:6s}  {n}  ->  {v}"
                if line in seen_lines:
                    continue
                seen_lines.add(line)
                print(line)


# ---------- SSDP ----------

def ssdp_probe(timeout: float):
    print(f"\n=== SSDP M-SEARCH ({len(SSDP_STS)} ST values, ~{timeout:.0f}s) ===")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    s.settimeout(0.4)
    s.bind(("", 0))
    sent = 0
    for st in SSDP_STS:
        msg = (
            "M-SEARCH * HTTP/1.1\r\n"
            "HOST: 239.255.255.250:1900\r\n"
            "MAN: \"ssdp:discover\"\r\n"
            "MX: 2\r\n"
            f"ST: {st}\r\n"
            "USER-AGENT: capsula-recon/1.0\r\n\r\n"
        ).encode("ascii")
        try:
            s.sendto(msg, SSDP_ADDR)
            sent += 1
        except OSError as e:
            print(f"  send-fail ST={st}: {e}")
    print(f"  sent {sent} M-SEARCHes from local port {s.getsockname()[1]}")
    deadline = time.time() + timeout
    by_host = {}
    while time.time() < deadline:
        try:
            data, addr = s.recvfrom(4096)
        except socket.timeout:
            continue
        text = data.decode("utf-8", errors="replace").strip()
        by_host.setdefault(addr[0], set()).add(text)
    s.close()

    if not by_host:
        print("  (no SSDP replies)")
        return
    for host in sorted(by_host):
        print(f"\n[SSDP] {host}")
        for blob in by_host[host]:
            for line in blob.splitlines():
                print(f"   {line}")
            print("   ---")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mdns-timeout", type=float, default=8.0)
    ap.add_argument("--ssdp-timeout", type=float, default=6.0)
    ap.add_argument("--skip-mdns", action="store_true")
    ap.add_argument("--skip-ssdp", action="store_true")
    args = ap.parse_args()

    print("Capsula Mini local discovery")
    print("Run from a host on the SAME LAN as 192.168.0.11.")
    print("If Windows Firewall asks, allow Python on Private networks.\n")

    if not args.skip_mdns:
        try:
            mdns_probe(args.mdns_timeout)
        except Exception as e:
            print(f"mDNS error: {e}")
    if not args.skip_ssdp:
        try:
            ssdp_probe(args.ssdp_timeout)
        except Exception as e:
            print(f"SSDP error: {e}")


if __name__ == "__main__":
    sys.exit(main())
