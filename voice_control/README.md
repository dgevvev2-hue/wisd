# Voice-controlled Capsula Mini via Bluetooth + Yandex.Music

Turns the Capsula Mini speaker into a BT audio sink and a Python service
on the PC does everything else:

```
you -> PC microphone -> Whisper (local) -> intent parser
                              |
               Yandex.Music search + MP3 download -> Player
                              |
                 Default Windows audio output (= Bluetooth to Capsula)
                              |
                       capsule plays the track
```

No VK account, no Spotify Premium, no firmware modification, no router MITM.

## One-time setup

### 1. Pair the Capsula as a Bluetooth speaker

1. On the Capsula: press and hold the volume-down button for 3 seconds
   until you hear "готова к сопряжению через Bluetooth" and the LED ring
   pulses blue.
2. On Windows: **Settings → Bluetooth & devices → Add device → Bluetooth**.
3. Pick `Capsula-mini-XXXXXXXXXXXXXXXX` from the list.
4. Once paired, the device shows up in **Sound settings → Output**
   as `Наушники (Capsula-mini-...)` — with the "Наушники" label even
   though it is a speaker (Windows always labels A2DP sinks that way).

### 2. Get a Yandex.Music token

Open this URL in a browser where you are **already logged in to Yandex**:

```
https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d
```

After "Allow" you will be redirected to a page whose URL contains
`#access_token=XXXXXXXXXXXXXXXXXXXXXXXXXXXX`. Copy just the token value
(without `access_token=` and without any `&token_type=...`).

### 3. Configure `config.json`

On first run, the script will create `config.json` and exit. Edit it:

```json
{
  "yandex_token": "ACTUAL_TOKEN_HERE",
  "whisper_model": "small",
  "whisper_compute_type": "int8",
  "whisper_device": "cpu",
  "language": "ru",
  "mic_index": null,
  "output_device_index": null,
  "require_wake_word": true,
  "wake_words": ["маруся", "ассистент", "робот", "алиса"]
}
```

Fields you might want to change:

| key | what it does |
|---|---|
| `yandex_token` | your OAuth token (required) |
| `whisper_model` | `tiny` / `base` / `small` / `medium` / `large-v3`. `small` is a good balance. |
| `whisper_compute_type` | `int8` (fast on CPU), `int8_float16` (if your CPU supports it), `float16` (GPU) |
| `whisper_device` | `cpu` or `cuda` |
| `mic_index` | integer from `_check_audio.py`. `null` = Windows default |
| `output_device_index` | output device index. `null` = Windows default. You **don't need** to set this if you set the Capsula as the default audio output in Windows. |
| `require_wake_word` | if `true`, the service only reacts to phrases starting with one of `wake_words` |

To list device indices:
```
python voice_control\_check_audio.py
```

### 4. Install dependencies (already done if you followed the earlier steps)

```
pip install faster-whisper sounddevice numpy yandex-music requests miniaudio yt-dlp
```

First run of `faster-whisper` will download the model (~250 MB for `small`).
Cache goes to `~/.cache/huggingface/`.

## Usage

### First: test Yandex token + download only

After editing `config.json`, run:

```
python voice_control\test_yandex.py "Linkin Park Numb"
```

Expected result:

```
[yandex] logged in as: ...
Search: 'Linkin Park Numb'
1. OK ...
[yandex] downloading ...
Downloaded: ...
OK
```

If this works, Yandex token/search/download is OK.

### Second: text-mode playback test

Set the Capsula as the **default Windows output device**, then run:

```
python voice_control\marusya_voice.py --text
```

Then type:

```
включи Linkin Park Numb
```

This bypasses Whisper and the microphone. If the Capsula plays music here,
the playback chain is OK.

### Third: full voice mode

```
python voice_control\marusya_voice.py
```

Then talk:

- `"Маруся, включи Linkin Park In The End"` — searches and plays
- `"Маруся, пауза"` — pauses current track (capsule keeps BT connection)
- `"Маруся, продолжай"` — resumes
- `"Маруся, следующий"` — skips (goes to next queued track if any)
- `"Маруся, громче"` / `"тише"` — software volume ±15%
- `"Маруся, громкость 50"` — set volume to 50%
- `"Маруся, стоп"` — stops + clears the queue
- `"Маруся, выход"` — shutdown the service

If you set `require_wake_word: false`, you can drop the `Маруся,` prefix.

### Volume levels

There are two volumes in play:

1. **Our software volume** (controlled by "громче"/"тише") — scales samples
   before sending to the audio device. Range 0-100%.
2. **Capsula's hardware volume** — set by the physical buttons on top of
   the speaker. Since we are streaming raw audio over BT, the speaker's
   own buttons work as usual.

They multiply. If the capsule is at 50% and our software is at 50%, the
actual loudness is ~25%.

## Troubleshooting

### "mic open, waiting for speech..." but nothing transcribes

- Try speaking louder / closer to mic
- Check `mic_index` in config (use a specific AMD Microphone Array index
  instead of `null` if the default mic is the BT headset)
- Lower `START_THRESHOLD` in `recognizer.py`

### Music plays through the PC speakers, not the Capsula

- Windows **Sound settings → Output** must have the Capsula as default,
  OR set `output_device_index` in config to the Capsula's index from
  `_check_audio.py`
- Make sure the Capsula is actually connected via BT, not just paired.
  Click the device in the BT menu and pick "Connect"

### "Yandex.Music init failed"

- Token expired or wrong
- Get a new token from the URL in step 2

### Track is "not available (licence/region)"

- Yandex restricts some tracks by region. Try a different version of the
  song or a live/remaster variant.

### BT audio cuts out / stutters

- BT range: ~10 m line-of-sight, less through walls
- Other 2.4 GHz interference (Wi-Fi, microwave) can break A2DP
- Try unpairing and repairing the device

## Files

- `marusya_voice.py` - entry point, orchestration
- `recognizer.py` - mic + VAD + Whisper
- `intents.py` - Russian intent parser
- `yandex.py` - Yandex.Music API wrapper
- `player.py` - miniaudio-based player with queue and volume
- `_check_audio.py` - list sound devices
- `config.json` - created on first run
- `cache/` - downloaded MP3s (safe to delete anytime; they re-download on next play)
