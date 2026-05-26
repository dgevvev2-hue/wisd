#!/usr/bin/env python3
"""
wisd auth helper.

Handles password hashing (PBKDF2-HMAC-SHA256) and signed session cookies
(payload + HMAC-SHA256 with a server-side key). Used by login.cgi /
logout.cgi / auth.cgi via subprocess.

The on-disk format for admin.json:
    {
        "user": "<username>",
        "passHash": "pbkdf2$<iters>$<salt_b64>$<hash_b64>"
    }

Session cookies are url-safe base64:
    <payload_b64>.<sig_b64>
where payload = <user>|<expires_unix_seconds>
and   sig     = HMAC-SHA256(payload, session.key)

The session.key is a 32-byte file at /var/lib/wisd/session.key. The CGI
runs as www-data; both files (admin.json, session.key) are 0640 wisd:www-data.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time

STATE_DIR = os.environ.get("WISD_STATE_DIR", "/var/lib/wisd")
ADMIN_FILE = os.path.join(STATE_DIR, "admin.json")
SESSION_KEY_FILE = os.path.join(STATE_DIR, "session.key")

# How long a session cookie is valid (in seconds).
SESSION_TTL = 15 * 24 * 3600  # 15 days

PBKDF2_ITERS = 200_000


def _b64u_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _load_session_key() -> bytes:
    with open(SESSION_KEY_FILE, "rb") as f:
        key = f.read().strip()
    if len(key) < 32:
        raise RuntimeError("session.key too short, regenerate")
    return key


def _load_admin() -> dict:
    with open(ADMIN_FILE) as f:
        return json.load(f)


def hash_password(plain: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, PBKDF2_ITERS)
    return f"pbkdf2${PBKDF2_ITERS}${_b64u_encode(salt)}${_b64u_encode(h)}"


def verify_password(stored: str, plain: str) -> bool:
    try:
        algo, iters, salt_b64, target_b64 = stored.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2":
        return False
    try:
        iters = int(iters)
        salt = _b64u_decode(salt_b64)
        target = _b64u_decode(target_b64)
    except Exception:
        return False
    h = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, iters)
    return hmac.compare_digest(h, target)


def issue_token(user: str, ttl: int = SESSION_TTL) -> str:
    key = _load_session_key()
    expires = int(time.time()) + ttl
    payload_raw = f"{user}|{expires}".encode("utf-8")
    sig = hmac.new(key, payload_raw, hashlib.sha256).digest()
    return f"{_b64u_encode(payload_raw)}.{_b64u_encode(sig)}"


def verify_token(token: str) -> dict | None:
    """Return {'user': ..., 'expires': ...} on success, None on failure."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload_raw = _b64u_decode(payload_b64)
        provided_sig = _b64u_decode(sig_b64)
    except Exception:
        return None
    try:
        key = _load_session_key()
    except FileNotFoundError:
        return None
    expected = hmac.new(key, payload_raw, hashlib.sha256).digest()
    if not hmac.compare_digest(provided_sig, expected):
        return None
    try:
        user, expires_s = payload_raw.decode("utf-8").split("|", 1)
        expires = int(expires_s)
    except Exception:
        return None
    if expires < time.time():
        return None
    return {"user": user, "expires": expires}


def cookie_from_http_cookie(http_cookie: str) -> str | None:
    """Pull the 'wisd_sess' cookie out of a raw Cookie header value."""
    if not http_cookie:
        return None
    for part in http_cookie.split(";"):
        kv = part.strip()
        if kv.startswith("wisd_sess="):
            return kv.split("=", 1)[1]
    return None


def main():
    """CLI shim, used by bash CGI scripts.

    Usage:
        wisd_auth.py hash <password>
        wisd_auth.py verify <stored_hash> <password>       # exit 0/1
        wisd_auth.py issue <user>                          # prints token
        wisd_auth.py check <token>                         # exit 0/1, prints user on stdout
        wisd_auth.py check_cookie <http_cookie_header>     # exit 0/1, prints user on stdout
    """
    if len(sys.argv) < 2:
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "hash":
        print(hash_password(sys.argv[2]))
    elif cmd == "verify":
        sys.exit(0 if verify_password(sys.argv[2], sys.argv[3]) else 1)
    elif cmd == "issue":
        print(issue_token(sys.argv[2]))
    elif cmd == "check":
        info = verify_token(sys.argv[2])
        if info is None:
            sys.exit(1)
        print(info["user"])
    elif cmd == "check_cookie":
        tok = cookie_from_http_cookie(sys.argv[2] if len(sys.argv) > 2 else "")
        if tok is None:
            sys.exit(1)
        info = verify_token(tok)
        if info is None:
            sys.exit(1)
        print(info["user"])
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
