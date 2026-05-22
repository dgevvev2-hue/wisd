"""
Intent parser for Russian voice commands.

Given a transcribed phrase, returns an Intent object:
  * Intent.kind  = one of 'play', 'pause', 'resume', 'stop', 'next', 'prev',
                          'volume_up', 'volume_down', 'volume_set', 'quit', 'unknown'
  * Intent.arg   = additional data (e.g. query string for 'play', volume level)

Parser is regex-first (cheap, no LLM needed) with a small keyword table.
Matches are case-insensitive and tolerate common filler words
("пожалуйста", "давай", "а ну", etc.).
"""
from __future__ import annotations
import re
from dataclasses import dataclass


@dataclass
class Intent:
    kind: str
    arg: str | int | None = None
    raw: str = ""

    def __bool__(self):
        return self.kind != "unknown"

    def __repr__(self):
        a = f" arg={self.arg!r}" if self.arg is not None else ""
        return f"<Intent {self.kind}{a}>"


# keyword tables. A "play" trigger followed by the actual query.
_PLAY_TRIGGERS = [
    r"вкл(?:ючи|ючай|юч[иь])",
    r"постав(?:ь|и|иш|ьте)",
    r"запусти",
    r"игра[йте]+",
    r"play",
]

_PAUSE = [r"пауза", r"поставь на паузу", r"останови(?:сь)?", r"приостанови", r"pause"]
_RESUME = [r"продолж(?:ай|и)", r"дальше играй", r"resume", r"возобнови"]
_STOP = [r"^стоп$", r"стоп музыка", r"выключи музыку", r"хватит", r"замолчи", r"^stop$"]
_NEXT = [r"следующ(?:ая|ую|ий)", r"дальше", r"переключи", r"next", r"скип"]
_PREV = [r"предыдущ(?:ая|ую|ий)", r"назад", r"previous", r"prev"]
_VOL_UP = [r"громче", r"прибавь", r"сделай громче", r"увеличь громкость", r"louder"]
_VOL_DOWN = [r"тише", r"убавь", r"сделай тише", r"уменьши громкость", r"quieter"]
_VOL_SET = [r"громкость\s+(\d{1,3})", r"поставь громкость\s+(\d{1,3})"]
_QUIT = [r"^выход$", r"выключи себя", r"заверши работу", r"^quit$", r"^exit$"]

_FILLER_PREFIX = re.compile(
    r"^\s*(?:пожалуйста[, ]*|слушай[, ]*|слыш[, ]*|"
    r"а ну[, ]*|давай[, ]*|эй[, ]*|маруся[, ]*|ассистент[, ]*)+",
    re.IGNORECASE,
)


def _any_match(text: str, patterns: list[str]) -> bool:
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return True
    return False


def _extract_query(text: str) -> str:
    """Strip a play-trigger prefix and return the rest as the query."""
    for p in _PLAY_TRIGGERS:
        m = re.search(p + r"\b\s*", text, re.IGNORECASE)
        if m:
            return text[m.end():].strip(" .,!?-—")
    return text.strip(" .,!?-—")


def parse(raw: str) -> Intent:
    if not raw:
        return Intent("unknown", raw=raw)
    text = raw.strip().lower()
    text = _FILLER_PREFIX.sub("", text)
    text = text.strip(" .,!?-—")
    if not text:
        return Intent("unknown", raw=raw)

    # order matters: pause/stop/next must beat 'play' on ambiguous phrases.
    if _any_match(text, _QUIT):
        return Intent("quit", raw=raw)
    if _any_match(text, _STOP):
        return Intent("stop", raw=raw)
    if _any_match(text, _PAUSE):
        return Intent("pause", raw=raw)
    if _any_match(text, _RESUME):
        return Intent("resume", raw=raw)
    if _any_match(text, _NEXT):
        return Intent("next", raw=raw)
    if _any_match(text, _PREV):
        return Intent("prev", raw=raw)
    for p in _VOL_SET:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            try:
                v = max(0, min(100, int(m.group(1))))
                return Intent("volume_set", arg=v, raw=raw)
            except ValueError:
                pass
    if _any_match(text, _VOL_UP):
        return Intent("volume_up", raw=raw)
    if _any_match(text, _VOL_DOWN):
        return Intent("volume_down", raw=raw)

    # if a play trigger was present, extract the query.
    if _any_match(text, _PLAY_TRIGGERS):
        q = _extract_query(text)
        if q:
            return Intent("play", arg=q, raw=raw)

    # fallback: bare phrase with no trigger. Treat very short phrases as unknown,
    # longer ones as a bare "play X" request (user said just the song).
    if len(text.split()) >= 2:
        return Intent("play", arg=text, raw=raw)
    return Intent("unknown", raw=raw)


if __name__ == "__main__":
    # smoke-test the parser
    examples = [
        "Маруся, включи Linkin Park In The End",
        "поставь пауза",
        "следующий",
        "громче",
        "громкость 50",
        "выключи музыку",
        "запусти Imagine Dragons",
        "пожалуйста продолжай",
        "давай Linkin Park",
        "Numb",
        "стоп",
        "",
        "какой-то случайный бред",
    ]
    for e in examples:
        print(f"  {e!r:55s} -> {parse(e)}")
