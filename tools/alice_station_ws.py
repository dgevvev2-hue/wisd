import argparse
import base64
import json
import os
import socket
import ssl
import struct
import time


def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            break
        data += chunk
    return data


def send_frame(sock, opcode, payload=b""):
    mask = os.urandom(4)
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    encoded = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(bytes(header) + mask + encoded)


def send_text(sock, text):
    send_frame(sock, 1, text.encode("utf-8"))


def recv_frame(sock, timeout=5):
    sock.settimeout(timeout)
    header = sock.recv(2)
    if not header:
        return None, b""
    opcode = header[0] & 0x0F
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(sock, 8))[0]
    masked = bool(header[1] & 0x80)
    mask = recv_exact(sock, 4) if masked else b""
    payload = recv_exact(sock, length)
    if masked:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return opcode, payload


def websocket_connect(host, port):
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    raw = socket.create_connection((host, port), timeout=6)
    sock = context.wrap_socket(raw, server_hostname=host)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET / HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "Origin: http://yandex.ru/\r\n"
        "X-Origin: http://yandex.ru/\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = sock.recv(2048).decode("utf-8", "replace")
    if "101 Switching Protocols" not in response:
        sock.close()
        raise RuntimeError(response.strip())
    return sock


def station_message(token, command, **payload):
    return {
        "conversationToken": token,
        "payload": {
            "command": command,
            **payload,
        },
    }


def send_station(host, port, message):
    with websocket_connect(host, port) as sock:
        send_text(sock, json.dumps(message, ensure_ascii=False, separators=(",", ":")))
        deadline = time.time() + 5
        replies = []
        while time.time() < deadline:
            try:
                opcode, payload = recv_frame(sock, timeout=1)
            except socket.timeout:
                continue
            if opcode is None:
                break
            if opcode == 9:
                send_frame(sock, 10, payload)
                continue
            if opcode == 8:
                replies.append(payload.decode("utf-8", "replace"))
                break
            if payload:
                replies.append(payload.decode("utf-8", "replace"))
        return replies


def main():
    parser = argparse.ArgumentParser(description="Local Yandex Station WebSocket client")
    parser.add_argument("--host", default="192.168.0.25")
    parser.add_argument("--port", default=1961, type=int)
    parser.add_argument("--token", default=os.environ.get("ALICE_TOKEN", ""))
    sub = parser.add_subparsers(dest="action", required=True)

    say = sub.add_parser("say")
    say.add_argument("text")

    volume = sub.add_parser("volume")
    volume.add_argument("value", type=int)

    sub.add_parser("stop-listening")

    args = parser.parse_args()
    if not args.token:
        raise SystemExit("Set --token or ALICE_TOKEN. The station returns 'Invalid token' without it.")

    if args.action == "say":
        message = station_message(args.token, "sendText", text=args.text)
    elif args.action == "volume":
        message = station_message(args.token, "setVolume", volume=max(0, min(10, args.value)))
    elif args.action == "stop-listening":
        message = station_message(
            args.token,
            "serverAction",
            serverActionEventPayload={"type": "server_action", "name": "on_suggest"},
        )
    else:
        raise SystemExit("Unknown action")

    for reply in send_station(args.host, args.port, message):
        print(reply)


if __name__ == "__main__":
    main()
