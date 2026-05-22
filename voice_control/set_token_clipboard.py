"""Write Yandex OAuth token from Windows clipboard into config.json."""
from __future__ import annotations

import json
import string
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
CONFIG_PATH = HERE / "config.json"

DEFAULT_CONFIG = {
    "yandex_token": "PUT_YOUR_TOKEN_HERE",
    "whisper_model": "small",
    "whisper_compute_type": "int8",
    "whisper_device": "cpu",
    "language": "ru",
    "mic_index": None,
    "output_device_index": None,
    "require_wake_word": True,
    "wake_words": ["маруся", "ассистент", "робот", "алиса"],
}


def get_clipboard() -> str:
    cp = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or "Get-Clipboard failed")
    return cp.stdout.strip()


def validate_token(token: str) -> bool:
    if token.startswith("OAuth "):
        token = token[6:].strip()
    if token.lower().startswith("authorization"):
        print("Clipboard contains an Authorization header. Copy only the token value.")
        return False
    if not token:
        print("Clipboard is empty.")
        return False
    if any(ch not in string.printable or ord(ch) < 32 for ch in token):
        print("Clipboard token contains control characters.")
        return False
    if len(token) < 40:
        print(f"Clipboard token is too short: {len(token)} chars.")
        return False
    if not token.startswith("y0_"):
        print("Clipboard does not look like a Yandex OAuth token: expected prefix y0_.")
        return False
    return True


def main() -> int:
    token = get_clipboard()
    if token.startswith("OAuth "):
        token = token[6:].strip()
    if not validate_token(token):
        return 1

    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        cfg = dict(DEFAULT_CONFIG)

    cfg["yandex_token"] = token
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved token to {CONFIG_PATH}")
    print(f"Token length: {len(token)} chars")
    print(f"Token preview: {token[:3]}...{token[-4:]}")
    print("Now run:")
    print(r"  py test_yandex.py \"Linkin Park Numb\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
