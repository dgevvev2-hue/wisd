"""
Audio player with a queue, pause/resume/skip/volume controls.

Uses miniaudio for decoding + a callback-driven PlaybackDevice so that
the audio output device works correctly even when it's an A2DP Bluetooth
sink (what the Capsula becomes when we pair it).

Audio flow:
  enqueue(mp3_path, title)
      |
      v
  player thread: decode MP3 -> int16 stereo PCM -> stream to PlaybackDevice
                              (software volume scaling applied per frame)

The PlaybackDevice is re-created per track because changing sample rate
between songs requires tearing the device down.
"""
from __future__ import annotations

import array
import threading
import time
from dataclasses import dataclass, field
from queue import Queue

import miniaudio


@dataclass
class Track:
    path: str
    title: str
    url: str | None = None


@dataclass
class _PlayerState:
    current: Track | None = None
    paused: bool = False
    volume: float = 0.8
    # flags signaled by controller thread
    skip: bool = False
    stop_all: bool = False


class Player:
    def __init__(self, output_device_index: int | None = None):
        # output_device_index is kept in the API for future use but miniaudio
        # has its own device enumeration (not the same as sounddevice/PortAudio),
        # so we always play to the Windows default output device.
        # To target the Capsula specifically, set it as the default output in
        # Windows Sound settings (see README).
        self.output_device_index = output_device_index
        self._queue: Queue[Track] = Queue()
        self._state = _PlayerState()
        self._state_lock = threading.Lock()
        self._wake = threading.Event()
        self._quit = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="player")
        self._thread.start()

    # -------- public API --------------------------------------------------

    @property
    def current(self) -> Track | None:
        with self._state_lock:
            return self._state.current

    @property
    def queued_count(self) -> int:
        return self._queue.qsize()

    def enqueue(self, track: Track) -> None:
        print(f"[player] enqueue: {track.title}")
        self._queue.put(track)
        self._wake.set()

    def pause(self) -> None:
        with self._state_lock:
            self._state.paused = True
        print("[player] paused")

    def resume(self) -> None:
        with self._state_lock:
            self._state.paused = False
        print("[player] resumed")

    def skip(self) -> None:
        with self._state_lock:
            self._state.skip = True
        print("[player] skipping current track")

    def stop(self) -> None:
        """Stop everything and clear the queue."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Exception:
                break
        with self._state_lock:
            self._state.stop_all = True
            self._state.paused = False
        print("[player] stopped + queue cleared")

    def set_volume(self, percent: int) -> None:
        v = max(0, min(100, int(percent))) / 100.0
        with self._state_lock:
            self._state.volume = v
        print(f"[player] volume -> {int(v*100)}%")

    def volume_up(self, step: int = 15) -> None:
        with self._state_lock:
            v = min(1.0, self._state.volume + step / 100.0)
            self._state.volume = v
        print(f"[player] volume up -> {int(v*100)}%")

    def volume_down(self, step: int = 15) -> None:
        with self._state_lock:
            v = max(0.0, self._state.volume - step / 100.0)
            self._state.volume = v
        print(f"[player] volume down -> {int(v*100)}%")

    def shutdown(self) -> None:
        self._quit = True
        self.stop()
        self._wake.set()
        self._thread.join(timeout=2.0)

    # -------- internal ----------------------------------------------------

    def _run(self) -> None:
        while not self._quit:
            try:
                track = self._queue.get(timeout=0.3)
            except Exception:
                continue
            if self._quit:
                return
            with self._state_lock:
                self._state.current = track
                self._state.skip = False
                self._state.stop_all = False
                self._state.paused = False
            try:
                self._play_one(track)
            except Exception as e:
                print(f"[player] error playing {track.title}: {type(e).__name__}: {e}")
            finally:
                with self._state_lock:
                    self._state.current = None

    def _play_one(self, track: Track) -> None:
        print(f"[player] decoding {track.path}")
        decoded = miniaudio.decode_file(
            track.path,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=2,
            sample_rate=44100,
        )
        samples: array.array = decoded.samples  # interleaved stereo int16
        total_frames = len(samples) // 2
        pos_frames = 0

        def generator():
            """miniaudio playback callback generator (required frames per step)."""
            nonlocal pos_frames
            required_frames = yield b""   # prime
            while True:
                with self._state_lock:
                    if self._state.stop_all or self._state.skip:
                        return
                    paused = self._state.paused
                    vol = self._state.volume
                if paused:
                    # emit silence while paused; keep pos_frames stable
                    silence = array.array("h", [0] * (required_frames * 2))
                    required_frames = yield silence.tobytes()
                    continue
                end = pos_frames + required_frames
                if end >= total_frames:
                    chunk = samples[pos_frames * 2: total_frames * 2]
                    actual_frames = len(chunk) // 2
                    pos_frames = total_frames
                    if vol != 1.0:
                        chunk = _apply_volume(chunk, vol)
                    missing_frames = max(0, required_frames - actual_frames)
                    yield chunk.tobytes() + b"\x00" * (missing_frames * 4)
                    return
                chunk = samples[pos_frames * 2: end * 2]
                pos_frames = end
                if vol != 1.0:
                    chunk = _apply_volume(chunk, vol)
                required_frames = yield chunk.tobytes()

        gen = generator()
        next(gen)  # prime
        device = miniaudio.PlaybackDevice(
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=2,
            sample_rate=44100,
        )
        device.start(gen)
        try:
            # block until track finishes or external command stops it
            while True:
                with self._state_lock:
                    if self._state.stop_all or self._state.skip:
                        break
                if pos_frames >= total_frames:
                    break
                time.sleep(0.05)
        finally:
            try:
                device.stop()
            except Exception:
                pass
            device.close()


def _apply_volume(samples: array.array, vol: float) -> array.array:
    # safe in-place-ish scaling for int16 stereo; clip on bounds
    out = array.array("h", (max(-32768, min(32767, int(s * vol))) for s in samples))
    return out


if __name__ == "__main__":
    # quick self-test: enqueue a file path passed on argv
    import sys
    if len(sys.argv) < 2:
        print("Usage: python player.py <path.mp3>")
        sys.exit(1)
    p = Player()
    p.enqueue(Track(path=sys.argv[1], title=sys.argv[1]))
    try:
        while p.current or p.queued_count:
            time.sleep(0.2)
    except KeyboardInterrupt:
        p.stop()
    p.shutdown()
