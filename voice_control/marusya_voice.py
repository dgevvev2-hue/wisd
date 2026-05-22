"""
Entry point for the voice-controlled music bridge.

Flow:
  mic -> Whisper -> intent parser -> dispatch:
      play X     -> Yandex.Music.find_and_download(X) -> Player.enqueue
      pause      -> Player.pause
      resume     -> Player.resume
      next       -> Player.skip
      stop       -> Player.stop
      volume_*   -> Player.set_volume / up / down
      quit       -> clean shutdown

Run:
  python marusya_voice.py
(first run creates config.json next to this file; edit it and re-run)
"""
from __future__ import annotations

import json
import re
import sys
import time
import argparse
from dataclasses import asdict
from pathlib import Path

from intents import Intent, parse as parse_intent
from player import Player, Track
from recognizer import VoiceRecognizer
from yandex import YandexMusic, YandexMusicError


HERE = Path(__file__).parent
CONFIG_PATH = HERE / "config.json"
CACHE_DIR = HERE / "cache"

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

WAKE_WORD_TOKEN = re.compile(
    r"^\s*(маруся|ассистент|робот|алиса)\b[\s,\.!?]*",
    re.IGNORECASE,
)


def load_or_create_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("=" * 70)
        print(f"Created default config at {CONFIG_PATH}")
        print("Edit it and set your Yandex OAuth token, then re-run.")
        print("Token URL:")
        print("  https://oauth.yandex.ru/authorize?response_type=token"
              "&client_id=23cabbbdc6cd418abb4b39c32c41195d")
        print("=" * 70)
        sys.exit(0)
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def has_wake_word(text: str, wake_words: list[str]) -> bool:
    low = text.lower().strip()
    for w in wake_words:
        if re.match(r"\s*" + re.escape(w.lower()) + r"\b", low):
            return True
    return False


def strip_wake_word(text: str) -> str:
    return WAKE_WORD_TOKEN.sub("", text, count=1).strip()


class Conductor:
    def __init__(self, cfg: dict, text_mode: bool = False):
        self.cfg = cfg
        print("[main] initialising Yandex.Music...")
        self.yandex = YandexMusic(
            token=cfg.get("yandex_token", ""),
            cache_dir=CACHE_DIR,
        )
        self.recognizer = None
        if not text_mode:
            print("[main] initialising Whisper...")
            self.recognizer = VoiceRecognizer(
                model_size=cfg.get("whisper_model", "small"),
                compute_type=cfg.get("whisper_compute_type", "int8"),
                device=cfg.get("whisper_device", "cpu"),
                mic_index=cfg.get("mic_index"),
                language=cfg.get("language", "ru"),
            )
        print("[main] initialising Player...")
        self.player = Player(output_device_index=cfg.get("output_device_index"))
        self.wake_words = cfg.get("wake_words", ["маруся"])
        self.require_wake = bool(cfg.get("require_wake_word", True))
        self._quit = False

    def run(self) -> None:
        print("\n" + "=" * 70)
        print("Ready. Say a command. Examples:")
        print('  "Маруся, включи Linkin Park Numb"')
        print('  "Маруся, пауза"    "Маруся, следующий"    "Маруся, громче"')
        print('  "Маруся, стоп"     "Маруся, выход"')
        print(f"  Wake word required: {self.require_wake}")
        print(f"  Wake words: {self.wake_words}")
        print("=" * 70 + "\n")
        if self.recognizer is None:
            print("[main] recognizer is not initialised")
            return
        for rec in self.recognizer.listen():
            if self._quit:
                break
            text = rec.text.strip()
            if not text:
                continue
            heard = f'[{rec.duration:.1f}s peak={rec.audio_rms_peak:.2f}] "{text}"'

            if self.require_wake:
                if not has_wake_word(text, self.wake_words):
                    print(f"  (ignored, no wake word) {heard}")
                    continue
                text = strip_wake_word(text)

            print(f"  HEARD {heard}")
            intent = parse_intent(text)
            print(f"  INTENT {intent}")

            try:
                self._dispatch(intent)
            except Exception as e:
                print(f"  [dispatch error] {type(e).__name__}: {e}")

    def run_text(self) -> None:
        print("\n" + "=" * 70)
        print("Text mode. Type commands instead of speaking.")
        print("Examples:")
        print("  включи Linkin Park Numb")
        print("  пауза")
        print("  продолжай")
        print("  следующий")
        print("  громкость 50")
        print("  стоп")
        print("  выход")
        print("=" * 70 + "\n")
        while not self._quit:
            try:
                text = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                continue
            if self.require_wake and has_wake_word(text, self.wake_words):
                text = strip_wake_word(text)
            intent = parse_intent(text)
            print(f"  INTENT {intent}")
            try:
                self._dispatch(intent)
            except Exception as e:
                print(f"  [dispatch error] {type(e).__name__}: {e}")

    def _dispatch(self, intent: Intent) -> None:
        kind = intent.kind
        if kind == "play":
            query = str(intent.arg or "").strip()
            if not query:
                print("  [play] empty query, ignoring")
                return
            found = self.yandex.find_and_download(query)
            if not found:
                print(f"  [play] nothing found for {query!r}")
                return
            track, path = found
            self.player.enqueue(Track(path=str(path), title=track.label()))
            print(f"  QUEUED: {track.label()}")
            return
        if kind == "pause":
            self.player.pause()
            return
        if kind == "resume":
            self.player.resume()
            return
        if kind == "stop":
            self.player.stop()
            return
        if kind == "next":
            self.player.skip()
            return
        if kind == "prev":
            print("  [prev] history not implemented yet")
            return
        if kind == "volume_up":
            self.player.volume_up()
            return
        if kind == "volume_down":
            self.player.volume_down()
            return
        if kind == "volume_set":
            self.player.set_volume(int(intent.arg or 50))
            return
        if kind == "quit":
            print("  [quit] stopping")
            self._quit = True
            if self.recognizer is not None:
                self.recognizer.stop()
            self.player.shutdown()
            return
        print(f"  [unknown intent] raw={intent.raw!r}")

    def shutdown(self) -> None:
        try:
            if self.recognizer is not None:
                self.recognizer.stop()
        except Exception:
            pass
        try:
            self.player.shutdown()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", action="store_true",
                    help="text command mode, no microphone/Whisper")
    args = ap.parse_args()

    cfg = load_or_create_config()
    try:
        c = Conductor(cfg, text_mode=args.text)
    except YandexMusicError as e:
        print(f"\n[fatal] {e}")
        return 2
    except Exception as e:
        print(f"\n[fatal] {type(e).__name__}: {e}")
        return 2

    try:
        if args.text:
            c.run_text()
        else:
            c.run()
    except KeyboardInterrupt:
        print("\n[main] Ctrl+C, stopping")
    finally:
        c.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
