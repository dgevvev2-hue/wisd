#!/usr/bin/env python3
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"


def load_config():
    if not CONFIG_PATH.exists():
        example = ROOT / "config.example.json"
        if example.exists():
            CONFIG_PATH.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        raise SystemExit("Создал config.json. Вставь туда bot_token от @BotFather и запусти снова.")
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not cfg.get("bot_token") or "PASTE_" in cfg.get("bot_token", ""):
        raise SystemExit("Вставь bot_token в telegram_router_bot/config.json")
    return cfg


CFG = load_config()
TOKEN = CFG["bot_token"].strip()
API = f"https://api.telegram.org/bot{TOKEN}"
ROUTER = CFG.get("router_base_url", "http://192.168.0.1:8083").rstrip("/")
TIMEOUT = int(CFG.get("request_timeout", 12))
ALLOWED = {int(x) for x in CFG.get("allowed_chat_ids", [])}


def http_json(url, timeout=TIMEOUT):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    return json.loads(raw)


def tg(method, data=None):
    payload = urllib.parse.urlencode(data or {}).encode()
    return http_json(f"{API}/{method}", timeout=35) if data is None else http_json_req(f"{API}/{method}", payload)


def http_json_req(url, payload):
    req = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=35) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def send(chat_id, text, keyboard=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
    if keyboard:
        data["reply_markup"] = json.dumps({"keyboard": keyboard, "resize_keyboard": True}, ensure_ascii=False)
    return tg("sendMessage", data)


def router(path, params=None):
    qs = urllib.parse.urlencode(params or {})
    url = f"{ROUTER}{path}" + (f"?{qs}" if qs else "")
    return http_json(url)


def vpn(action, **params):
    params = {"action": action, **params}
    return router("/cgi-bin/vpn.cgi", params)


def safe_chat(chat_id):
    return not ALLOWED or int(chat_id) in ALLOWED


def fmt_status():
    s = vpn("status")
    mode = s.get("mode", "?").upper()
    enabled = "ON" if s.get("enabled") else "OFF"
    nat = "ON" if s.get("nat") else "OFF"
    elapsed = int(s.get("elapsed") or 0)
    hh, rem = divmod(elapsed, 3600)
    mm, ss = divmod(rem, 60)
    return (
        f"<b>Router VPN</b>\n"
        f"VPN: <b>{enabled}</b>\n"
        f"Mode: <b>{mode}</b>\n"
        f"NAT tunnel: <b>{nat}</b>\n"
        f"Server ID: <b>{s.get('id') or '-'}</b>\n"
        f"Host: <code>{s.get('host') or '-'}</code>\n"
        f"Ping: <b>{s.get('ping') or '?'} ms</b>\n"
        f"Uptime: <b>{hh:02}:{mm:02}:{ss:02}</b>"
    )


def fmt_dns():
    d = router("/cgi-bin/dns.cgi", {"action": "status"})
    return (
        f"<b>DNS защита</b>\n"
        f"Mode: <b>{d.get('mode')}</b>\n"
        f"Resolvers: <code>{d.get('resolvers')}</code>\n"
        f"DNS redirect: <b>{'ON' if d.get('dnsRedirect') else 'OFF'}</b>\n"
        f"DoT block: <b>{'ON' if d.get('dotBlock') else 'OFF'}</b>\n"
        f"Ad block: <b>{'ON' if d.get('adBlock') else 'OFF'}</b>"
    )


def fmt_servers(limit=12):
    data = http_json(f"{ROUTER}/nodes.json")
    rows = data[:limit] if isinstance(data, list) else data.get("nodes", [])[:limit]
    out = ["<b>Серверы</b>"]
    for n in rows:
        out.append(f"{n.get('id')}: {n.get('name')} | {n.get('ping', '?')} ms | <code>{n.get('host')}</code>")
    return "\n".join(out)


def main_keyboard():
    return [
        ["Статус", "Туннель ON", "Прокси ON"],
        ["Выключить VPN", "Перезапуск VPN"],
        ["Серверы", "Ping", "DNS защита"],
        ["Auto ON", "Auto OFF", "Info"],
        ["Помощь"],
    ]


def handle(chat_id, text):
    t = (text or "").strip()
    low = t.lower()
    if low in {"/start", "start", "пуск"}:
        if not ALLOWED:
            return send(chat_id, f"Твой chat_id: <code>{chat_id}</code>\nДобавь его в allowed_chat_ids для защиты.", main_keyboard())
        return send(chat_id, fmt_status(), main_keyboard())
    if not safe_chat(chat_id):
        return send(chat_id, f"Доступ закрыт. chat_id: <code>{chat_id}</code>")
    if low in {"/help", "help", "помощь"}:
        return send(chat_id, HELP, main_keyboard())
    if low in {"/status", "статус"}:
        return send(chat_id, fmt_status(), main_keyboard())
    if low in {"туннель on", "/tunnel"}:
        sid = str(CFG.get("default_server_id", 0))
        res = vpn("connect", id=sid, mode="tunnel")
        return send(chat_id, "Туннель включён.\n\n" + fmt_status(), main_keyboard())
    if low in {"прокси on", "/proxy"}:
        sid = str(CFG.get("default_server_id", 0))
        vpn("connect", id=sid, mode="proxy")
        return send(chat_id, "Прокси включён.\n\n" + fmt_status(), main_keyboard())
    if low in {"выключить vpn", "/off", "/disconnect"}:
        vpn("disconnect")
        return send(chat_id, "VPN выключен.", main_keyboard())
    if low in {"перезапуск vpn", "/restart"}:
        vpn("restart")
        return send(chat_id, "VPN перезапущен.\n\n" + fmt_status(), main_keyboard())
    if low in {"серверы", "/servers"}:
        return send(chat_id, fmt_servers(), main_keyboard())
    if low.startswith("/connect "):
        parts = low.split()
        sid = parts[1]
        mode = parts[2] if len(parts) > 2 and parts[2] in {"tunnel", "proxy"} else CFG.get("default_mode", "tunnel")
        vpn("connect", id=sid, mode=mode)
        return send(chat_id, f"Подключил server {sid}, mode {mode}.\n\n" + fmt_status(), main_keyboard())
    if low in {"ping", "/ping"}:
        p = router("/cgi-bin/ping.cgi", {"host": "8.8.8.8"})
        return send(chat_id, f"Ping 8.8.8.8: <b>{p.get('ping', 'timeout')}</b> ms", main_keyboard())
    if low.startswith("/ping "):
        host = t.split(maxsplit=1)[1]
        p = router("/cgi-bin/ping.cgi", {"host": host})
        return send(chat_id, f"Ping {p.get('host')}: <b>{p.get('ping', 'timeout')}</b> ms", main_keyboard())
    if low in {"dns защита", "/dns"}:
        return send(chat_id, fmt_dns(), main_keyboard())
    if low.startswith("/dns "):
        mode = low.split(maxsplit=1)[1]
        if mode not in {"full", "adguard", "quad9", "provider"}:
            return send(chat_id, "DNS режимы: full, adguard, quad9, provider", main_keyboard())
        router("/cgi-bin/dns.cgi", {"action": "apply", "mode": mode})
        return send(chat_id, fmt_dns(), main_keyboard())
    if low in {"auto on", "/auto_on"}:
        router("/cgi-bin/auto.cgi", {"action": "start", "threshold": "100", "interval": "600"})
        return send(chat_id, "Auto switch включён: порог 100 ms, проверка 10 min.", main_keyboard())
    if low in {"auto off", "/auto_off"}:
        router("/cgi-bin/auto.cgi", {"action": "stop"})
        return send(chat_id, "Auto switch выключен.", main_keyboard())
    if low in {"info", "/info"}:
        i = router("/cgi-bin/info.cgi")
        return send(chat_id, f"<b>Info</b>\nLoad: <b>{i.get('load')}</b>\nDevices: <b>{len(i.get('devices', []))}</b>\nVPN: <b>{'ON' if i.get('services', {}).get('vpn') else 'OFF'}</b>", main_keyboard())
    return send(chat_id, "Не понял команду. Нажми «Помощь».", main_keyboard())


HELP = """<b>Команды</b>
/status - статус VPN
/servers - список серверов
/connect 0 tunnel - включить сервер 0 туннелем
/connect 0 proxy - включить сервер 0 прокси
/off - выключить VPN
/restart - перезапустить VPN
/ping ya.ru - ping сайта
/dns full - DNS защита full
/dns provider - вернуть DNS провайдера
/auto_on - автопереключение VPN
/auto_off - выключить авто
/info - роутер и устройства
"""


def poll():
    offset = 0
    print("Router VPN Telegram bot started")
    while True:
        try:
            updates = tg("getUpdates", {"timeout": 30, "offset": offset + 1}).get("result", [])
            for u in updates:
                offset = max(offset, int(u["update_id"]))
                msg = u.get("message") or u.get("edited_message") or {}
                chat = msg.get("chat", {})
                text = msg.get("text", "")
                if chat.get("id"):
                    handle(int(chat["id"]), text)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            print("net error:", e)
            time.sleep(4)
        except KeyboardInterrupt:
            print("stopped")
            return
        except Exception as e:
            print("error:", repr(e))
            time.sleep(4)


if __name__ == "__main__":
    poll()
