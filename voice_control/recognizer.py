"""
Microphone + VAD + faster-whisper transcription.

Implements a continuous listener that:
  * captures audio from the mic at 16 kHz mono float32
  * uses a simple energy-based VAD to segment utterances
  * transcribes each utterance with faster-whisper
  * yields the recognised text (as an iterator)

Why not Silero VAD / Porcupine wake-word?
  * Silero would pull in torch (400 MB, heavy)
  * Porcupine requires a paid "Маруся" keyword
  * Energy VAD is 30 lines and works well in a quiet room. The wake-word
    filter is done later by the intent parser, which strips 'маруся' prefix.
"""
from __future__ import annotations

import queue
import sys
import time
from dataclasses import dataclass

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel


SAMPLE_RATE = 16_000
BLOCK_MS = 50                # mic callback granularity
BLOCK_FRAMES = SAMPLE_RATE * BLOCK_MS // 1000

# VAD thresholds (RMS amplitude over the block, on float32 [-1, 1])
START_THRESHOLD = 0.012      # start recording when RMS crosses this
CONTINUE_THRESHOLD = 0.006   # keep recording while above this
MIN_UTTERANCE_SEC = 0.4      # reject shorter = probably noise
MAX_UTTERANCE_SEC = 20.0     # safety cap
SILENCE_TAIL_SEC = 0.8       # how long silence before we close the utterance
PRE_ROLL_SEC = 0.25          # include a bit of audio before speech started


@dataclass
class Recognition:
    text: str
    duration: float
    audio_rms_peak: float


class VoiceRecognizer:
    def __init__(
        self,
        model_size: str = "small",
        compute_type: str = "int8",
        device: str = "cpu",
        mic_index: int | None = None,
        language: str = "ru",
    ):
        self.language = language
        self.mic_index = mic_index
        print(f"[recognizer] loading faster-whisper '{model_size}' ({compute_type})")
        t0 = time.time()
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        print(f"[recognizer] model ready in {time.time() - t0:.1f}s")
        self._stop = False

    # ----- mic capture state machine --------------------------------------

    def _pcm_stream(self):
        """Yield utterance np.ndarrays (float32 mono 16 kHz)."""
        q: queue.Queue = queue.Queue()

        def _cb(indata, frames, time_info, status):
            if status:
                # overflow / dropout — log but keep going
                print(f"[recognizer] audio callback status: {status}", file=sys.stderr)
            q.put(indata[:, 0].copy())

        pre_roll = int(PRE_ROLL_SEC * SAMPLE_RATE)
        silence_tail = int(SILENCE_TAIL_SEC * SAMPLE_RATE / BLOCK_FRAMES)
        min_frames = int(MIN_UTTERANCE_SEC * SAMPLE_RATE)
        max_frames = int(MAX_UTTERANCE_SEC * SAMPLE_RATE)

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_FRAMES,
            channels=1,
            dtype="float32",
            device=self.mic_index,
            callback=_cb,
        ):
            print("[recognizer] mic open, waiting for speech...")

            ring: list[np.ndarray] = []           # pre-roll ring buffer
            ring_max = max(1, pre_roll // BLOCK_FRAMES)

            recording: list[np.ndarray] = []      # active utterance buffer
            silent_blocks = 0
            in_utt = False

            while not self._stop:
                try:
                    block = q.get(timeout=0.3)
                except queue.Empty:
                    continue
                rms = float(np.sqrt(np.mean(block * block) + 1e-12))

                if not in_utt:
                    ring.append(block)
                    if len(ring) > ring_max:
                        ring.pop(0)
                    if rms >= START_THRESHOLD:
                        recording = list(ring)     # seed with pre-roll
                        recording.append(block)
                        silent_blocks = 0
                        in_utt = True
                else:
                    recording.append(block)
                    if rms < CONTINUE_THRESHOLD:
                        silent_blocks += 1
                    else:
                        silent_blocks = 0
                    total_frames = sum(b.shape[0] for b in recording)
                    if silent_blocks >= silence_tail or total_frames >= max_frames:
                        audio = np.concatenate(recording)
                        in_utt = False
                        recording = []
                        silent_blocks = 0
                        ring.clear()
                        if audio.shape[0] >= min_frames:
                            yield audio

    # ----- public API ------------------------------------------------------

    def listen(self):
        """Iterator of Recognition objects, one per detected utterance."""
        for audio in self._pcm_stream():
            peak = float(np.max(np.abs(audio)))
            t0 = time.time()
            segments, _info = self.model.transcribe(
                audio,
                language=self.language,
                beam_size=1,
                vad_filter=False,          # we already did VAD
                condition_on_previous_text=False,
                no_speech_threshold=0.6,
            )
            text = " ".join(s.text for s in segments).strip()
            dur = time.time() - t0
            if not text:
                continue
            yield Recognition(text=text, duration=dur, audio_rms_peak=peak)

    def stop(self):
        self._stop = True


if __name__ == "__main__":
    print("Smoke test: will transcribe until you say 'выход' or press Ctrl+C.")
    r = VoiceRecognizer(model_size="small")
    try:
        for rec in r.listen():
            print(f"  [{rec.duration:.1f}s peak={rec.audio_rms_peak:.3f}] {rec.text!r}")
            if "выход" in rec.text.lower() or "exit" in rec.text.lower():
                break
    except KeyboardInterrupt:
        pass
