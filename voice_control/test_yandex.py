"""Quick Yandex.Music token/search/download test."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from yandex import YandexMusic, YandexMusicError

HERE = Path(__file__).parent
cfg_path = HERE / "config.json"

if not cfg_path.exists():
    print(f"No config.json: {cfg_path}")
    print("Run: python marusya_voice.py")
    sys.exit(2)

cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
query = " ".join(sys.argv[1:]) or "Linkin Park Numb"

try:
    ym = YandexMusic(cfg.get("yandex_token", ""), HERE / "cache")
except YandexMusicError as e:
    print("ERROR:")
    print(e)
    sys.exit(2)

print(f"\nSearch: {query!r}\n")
for i, t in enumerate(ym.search(query, limit=5), 1):
    print(f"{i}. {'OK' if t.available else 'BLOCKED'}  {t.id}  {t.label()}")

found = ym.find_and_download(query)
if not found:
    print("\nNo playable track found/downloaded")
    sys.exit(1)
track, path = found
print(f"\nDownloaded: {track.label()}")
print(f"Path: {path}")
print("OK")
