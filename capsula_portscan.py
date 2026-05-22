#!/usr/bin/env python3
"""
Full TCP port scan of the Capsula Mini.

Goal: find any service the device hides on a non-standard port -
dropbear/SSH on 2222/22222, telnet on 23, ADB on 5555, mosquitto on 1883,
debug HTTP on 7681/8000/8888, etc. Per-port concurrency is safe even
though :80 application is fragile, because each port is its own socket.

Pure stdlib. TCP connect scan only (no SYN, no admin needed).

Usage:
    python capsula_portscan.py
    python capsula_portscan.py --host 192.168.0.11 --start 1 --end 65535
    python capsula_portscan.py --top1000          # only top-1000 IANA list
    python capsula_portscan.py --threads 512 --timeout 0.8
"""
import argparse
import concurrent.futures as futures
import json
import os
import socket
import sys
import time

DEFAULT_HOST = "192.168.0.11"

# A practical "top-1000-ish" set: standard services + things that often
# show up on embedded/IoT/Android-based smart speakers.
TOP_PORTS = sorted(set([
    # standard
    7, 9, 13, 17, 19, 21, 22, 23, 25, 37, 53, 67, 68, 69, 79, 80, 81, 82,
    88, 102, 110, 111, 113, 119, 123, 135, 137, 138, 139, 143, 161, 162,
    179, 199, 389, 427, 443, 444, 445, 464, 465, 500, 513, 514, 515, 520,
    523, 548, 554, 587, 593, 623, 631, 636, 666, 873, 902, 990, 993, 995,
    # web alt
    1080, 1234, 1337, 1433, 1521, 1604, 1700, 1701, 1723, 1755, 1812, 1813,
    1883, 1900, 1935, 2000, 2001, 2049, 2082, 2083, 2086, 2087,
    2095, 2096, 2121, 2181, 2222, 2375, 2376, 2380, 2401,
    2525, 2552, 2628, 2638, 3000, 3001, 3128, 3260, 3268, 3269, 3306,
    3333, 3389, 3478, 3479, 3517, 3689, 3690, 3702, 3784, 3790, 3838,
    4000, 4040, 4045, 4242, 4369, 4433, 4443, 4444, 4500, 4567, 4711,
    4848, 4899, 5000, 5001, 5060, 5061, 5222, 5269, 5280, 5353, 5355,
    5432, 5500, 5555, 5556, 5601, 5631, 5666, 5672, 5683, 5684, 5800,
    5801, 5900, 5901, 5984, 5985, 5986, 6000, 6379, 6443, 6463, 6464,
    6465, 6666, 6667, 6881, 6969, 7000, 7001, 7002, 7070, 7100, 7547,
    7654, 7676, 7681, 7777, 7779, 7800, 7900, 8000, 8001, 8008, 8009,
    8010, 8020, 8030, 8040, 8042, 8050, 8060, 8069, 8080, 8081, 8082,
    8083, 8084, 8085, 8086, 8087, 8088, 8089, 8090, 8091, 8092, 8095,
    8096, 8097, 8098, 8099, 8100, 8123, 8126, 8161, 8181, 8200, 8222,
    8243, 8280, 8333, 8334, 8400, 8443, 8444, 8500, 8501, 8554, 8555,
    8585, 8649, 8700, 8765, 8800, 8843, 8866, 8880, 8881, 8888, 8983,
    9000, 9001, 9002, 9009, 9010, 9042, 9080, 9090, 9091, 9092, 9100,
    9200, 9201, 9300, 9418, 9443, 9595, 9696, 9999, 10000, 10001, 10010,
    10243, 10250, 11211, 11434, 12345, 13720, 13721, 14000, 15000, 16000,
    16080, 16992, 17000, 17500, 18000, 18080, 18181, 19000, 19132, 19999,
    20000, 22222, 23000, 24800, 25565, 25672, 26656, 27017, 27018, 27019,
    28015, 28017, 28960, 30000, 30005, 31337, 32400, 32768, 32769, 33060,
    34567, 35729, 41194, 42424, 49152, 49153, 49154, 49155, 49156, 49157,
    49158, 49159, 49160, 49161, 49162, 49163, 49164, 49165, 49166, 49167,
    49168, 49169, 49170, 49171, 49172, 49173, 50000, 50050, 50070, 51234,
    52869, 54321, 55555, 60000, 60001, 61000, 62078, 64000, 64738, 65000,
    65535,
]))


def scan_port(host, port, timeout):
    """Return port if open, else None. Also returns banner if any."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        rc = s.connect_ex((host, port))
        if rc != 0:
            s.close()
            return None
        banner = b""
        try:
            s.settimeout(0.4)
            banner = s.recv(256)
        except (socket.timeout, OSError):
            pass
        s.close()
        return {"port": port, "banner": banner.decode("latin-1", errors="replace").strip()}
    except OSError:
        return None


def scan(host, ports, threads, timeout):
    started = time.time()
    open_ports = []
    done = 0
    total = len(ports)
    print(f"Scanning {host}: {total} ports, {threads} threads, timeout {timeout}s")
    with futures.ThreadPoolExecutor(max_workers=threads) as ex:
        future_to_port = {ex.submit(scan_port, host, p, timeout): p for p in ports}
        for fut in futures.as_completed(future_to_port):
            done += 1
            r = fut.result()
            if r:
                open_ports.append(r)
                banner = r["banner"]
                if banner:
                    banner = banner.replace("\r", " ").replace("\n", " ")[:80]
                    print(f"  OPEN  {r['port']:5d}   banner: {banner!r}")
                else:
                    print(f"  OPEN  {r['port']:5d}")
            if done % 1000 == 0 or done == total:
                elapsed = time.time() - started
                rate = done / elapsed if elapsed else 0
                print(f"  ... {done}/{total} done in {elapsed:.1f}s ({rate:.0f} ports/s)")
    open_ports.sort(key=lambda r: r["port"])
    return {"host": host, "open_ports": open_ports, "total_scanned": total,
            "elapsed_sec": round(time.time() - started, 2)}


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.join(script_dir, "capsula_portscan_results.json")

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=65535)
    ap.add_argument("--top1000", action="store_true",
                    help="only scan the curated TOP_PORTS list (~350 ports)")
    ap.add_argument("--threads", type=int, default=512)
    ap.add_argument("--timeout", type=float, default=1.0)
    ap.add_argument("--out", default=default_out)
    args = ap.parse_args()

    if args.top1000:
        ports = TOP_PORTS
    else:
        ports = list(range(args.start, args.end + 1))

    out_path = os.path.abspath(args.out)
    print(f"Capsula port scan -> {args.host}")
    print(f"Output: {out_path}")
    result = scan(args.host, ports, args.threads, args.timeout)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nFinished in {result['elapsed_sec']}s")
    print(f"OPEN ports ({len(result['open_ports'])}):")
    for r in result["open_ports"]:
        b = r["banner"][:100] if r["banner"] else ""
        print(f"  {r['port']:5d}   {b}")
    print(f"\nResults: {out_path}")


if __name__ == "__main__":
    sys.exit(main())
