"""Safely write Yandex OAuth token into config.json without echoing it."""
from __future__ import annotations

import getpass
import json
import argparse
import string
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--visible", action="store_true",
                    help="use normal visible input; easier to paste in cmd.exe")
    args = ap.parse_args()

    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        cfg = dict(DEFAULT_CONFIG)

    if args.visible:
        token = input("Paste Yandex OAuth token (visible input): ").strip()
    else:
        token = getpass.getpass("Paste Yandex OAuth token (hidden input): ").strip()
    if not token:
        print("Empty token, nothing changed.")
        return 1
    if any(ch not in string.printable or ord(ch) < 32 for ch in token):
        print("Token contains control characters, not writing it.")
        print("If you used Ctrl+V in cmd.exe, run again with:")
        print("  python set_token.py --visible")
        return 1
    if len(token) < 40:
        print(f"Token is too short ({len(token)} chars), not writing it.")
        print("You likely pasted only part of the token.")
        return 1
    if not token.startswith("y0_"):
        print("Warning: token does not start with y0_. Writing anyway.")

    cfg["yandex_token"] = token
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Token saved to {CONFIG_PATH}")
    print("Next test:")
    print(r"  python test_yandex.py \"Linkin Park Numb\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
