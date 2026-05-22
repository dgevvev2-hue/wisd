"""
Yandex.Music wrapper: search by free-text query, download a matching track
to a local cache, and return the local MP3 path.

Why cache on disk:
  * miniaudio decode is faster from a file than from a stream
  * repeat requests for the same song are instant
  * we can keep files around for offline replay

Token acquisition (do this ONCE, paste into config.json):
  Open in a browser (must be logged into Yandex):
    https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d
  After login you will be redirected to a yandex page whose URL contains
  '#access_token=XXXXXXXXXX'. Copy the access_token value into config.json.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from yandex_music import Client


@dataclass
class TrackInfo:
    id: str
    title: str
    artists: str
    duration_sec: int
    available: bool

    def label(self) -> str:
        m, s = divmod(self.duration_sec, 60)
        return f"{self.artists} — {self.title} ({m}:{s:02d})"


class YandexMusicError(Exception):
    pass


class YandexMusic:
    def __init__(self, token: str, cache_dir: Path):
        if not token or token.strip() in ("", "PUT_YOUR_TOKEN_HERE"):
            raise YandexMusicError(
                "Yandex OAuth token is missing. Get one from:\n"
                "  https://oauth.yandex.ru/authorize?response_type=token"
                "&client_id=23cabbbdc6cd418abb4b39c32c41195d\n"
                "and paste the access_token into config.json."
            )
        self._token = token
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        print("[yandex] initialising Yandex.Music client...")
        try:
            self.client = Client(token).init()
        except Exception as e:
            raise YandexMusicError(
                f"Yandex.Music init failed ({type(e).__name__}: {e}). "
                "Is the token valid and not expired?"
            ) from e
        # sanity: what's the account
        try:
            me = self.client.me
            acc = getattr(me, "account", None) if me else None
            name = getattr(acc, "display_name", "?") if acc else "?"
            print(f"[yandex] logged in as: {name}")
        except Exception:
            print("[yandex] logged in (account info unavailable)")

    # ------------------------------------------------------------------

    def search_one(self, query: str) -> TrackInfo | None:
        """Return the single best-matching track for `query`, or None."""
        print(f"[yandex] searching: {query!r}")
        try:
            result = self.client.search(query, type_="track", nocorrect=False)
        except Exception as e:
            print(f"[yandex] search error: {type(e).__name__}: {e}")
            return None

        track = None
        if result and result.best and result.best.result:
            candidate = result.best.result
            # best.result for type=track may still be a Track or something else
            if hasattr(candidate, "id") and hasattr(candidate, "artists"):
                track = candidate
        if track is None and result and result.tracks and result.tracks.results:
            track = result.tracks.results[0]
        if track is None:
            return None

        return _to_trackinfo(track)

    def search(self, query: str, limit: int = 5) -> list[TrackInfo]:
        print(f"[yandex] searching (top {limit}): {query!r}")
        try:
            result = self.client.search(query, type_="track", nocorrect=False)
        except Exception as e:
            print(f"[yandex] search error: {type(e).__name__}: {e}")
            return []
        items = []
        if result and result.tracks and result.tracks.results:
            for t in result.tracks.results[:limit]:
                items.append(_to_trackinfo(t))
        return items

    # ------------------------------------------------------------------

    def download(self, track_id: str) -> Path | None:
        """Return a local MP3 path for the given track, caching the file."""
        safe_id = re.sub(r"[^0-9a-zA-Z:_-]", "_", str(track_id))
        target = self.cache_dir / f"{safe_id}.mp3"
        if target.exists() and target.stat().st_size > 1024:
            print(f"[yandex] cache hit: {target.name}")
            return target

        try:
            tracks = self.client.tracks([track_id])
        except Exception as e:
            print(f"[yandex] lookup error: {type(e).__name__}: {e}")
            return None
        if not tracks:
            print("[yandex] track not found")
            return None
        track = tracks[0]
        if not getattr(track, "available", True):
            print("[yandex] track not available for playback (licence/region)")
            return None

        try:
            dl_infos = track.get_download_info()
        except Exception as e:
            print(f"[yandex] download_info error: {type(e).__name__}: {e}")
            return None
        if not dl_infos:
            print("[yandex] no download info")
            return None
        # prefer mp3, highest bitrate
        mp3_infos = [d for d in dl_infos if getattr(d, "codec", "mp3") == "mp3"] or dl_infos
        best = max(mp3_infos, key=lambda d: getattr(d, "bitrate_in_kbps", 0))

        tmp = target.with_suffix(".mp3.part")
        print(f"[yandex] downloading {getattr(best, 'bitrate_in_kbps', '?')}kbps -> {target.name}")
        t0 = time.time()
        try:
            best.download(str(tmp))
        except Exception as e:
            print(f"[yandex] download error: {type(e).__name__}: {e}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            return None
        try:
            os.replace(tmp, target)
        except Exception as e:
            print(f"[yandex] rename error: {e}")
            return None
        size_kb = target.stat().st_size / 1024
        print(f"[yandex] done in {time.time() - t0:.1f}s, {size_kb:.0f} KB")
        return target

    def find_and_download(self, query: str) -> tuple[TrackInfo, Path] | None:
        t = self.search_one(query)
        if t is None:
            return None
        if not t.available:
            # try next best instead of failing
            candidates = self.search(query, limit=5)
            next_avail = next((c for c in candidates if c.available), None)
            if next_avail is None:
                print(f"[yandex] no available track for {query!r}")
                return None
            t = next_avail
        path = self.download(t.id)
        if path is None:
            return None
        return t, path


def _to_trackinfo(track) -> TrackInfo:
    artists = ", ".join(
        getattr(a, "name", "?") for a in (getattr(track, "artists", []) or [])
    ) or "Unknown"
    dur_ms = int(getattr(track, "duration_ms", 0) or 0)
    return TrackInfo(
        id=str(track.id),
        title=getattr(track, "title", "Unknown"),
        artists=artists,
        duration_sec=dur_ms // 1000,
        available=bool(getattr(track, "available", True)),
    )


if __name__ == "__main__":
    # quick smoke test: requires config.json with a token
    import json
    import sys

    cfg_path = Path(__file__).parent / "config.json"
    if not cfg_path.exists():
        print(f"No config.json at {cfg_path} - create one with your token first.")
        sys.exit(1)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    token = cfg.get("yandex_token", "")
    try:
        y = YandexMusic(token=token, cache_dir=Path(__file__).parent / "cache")
    except YandexMusicError as e:
        print(e)
        sys.exit(1)
    q = " ".join(sys.argv[1:]) or "Linkin Park Numb"
    print(f"\nSearch query: {q!r}\n")
    for t in y.search(q, limit=5):
        print(f"  [{t.available and ' ok ' or 'BLCK'}]  id={t.id}  {t.label()}")
    found = y.find_and_download(q)
    if found:
        track, path = found
        print(f"\nDOWNLOADED: {track.label()}")
        print(f"PATH: {path}")
    else:
        print("\nNo track downloaded")
