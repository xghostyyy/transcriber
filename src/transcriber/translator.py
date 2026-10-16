"""Перевод текста через deep-translator (бесплатный Google, без ключей)."""

from __future__ import annotations

import re
import time
from typing import Callable, Optional, Sequence

from deep_translator import GoogleTranslator

from .transcriber import Segment

MAX_CHUNK_CHARS = 4000      # лимит бесплатного эндпоинта Google ~5000 символов
SEGMENT_BATCH_CHARS = 3200  # размер батча при переводе субтитров
SEGMENT_BATCH_MAX = 30      # максимум реплик в одном батче

_CODE_MAP = {"he": "iw", "zh": "zh-CN", "jv": "jw"}
_MARKER_RE = re.compile(r"\[\[\s*(\d+)\s*\]\]")


class TranslationError(Exception):
    """Понятная человеку ошибка перевода."""


def _google_code(code: str) -> str:
    return _CODE_MAP.get(code, code)


def _with_retries(func: Callable[[], str], what: str = "перевести текст") -> str:
    last: Optional[Exception] = None
    for attempt in range(4):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 — сеть/лимиты бывают разные
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise TranslationError(f"Не удалось {what}: {last}")


def split_into_chunks(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Режет текст на куски не длиннее limit символов по строкам и предложениям."""
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    def push(piece: str) -> None:
        nonlocal current
        piece = piece.strip()
        if not piece:
            return
        if len(current) + len(piece) + (1 if current else 0) <= limit:
            current = f"{current}\n{piece}" if current else piece
            return
        flush()
        while len(piece) > limit:  # кусок сам больше лимита — режем по словам
            cut = piece.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            chunks.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        current = piece

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if len(line) <= limit:
            push(line)
        else:
            for sentence in re.split(r"(?<=[.!?…])\s+", line):
                push(sentence)
    flush()
    return chunks


def translate_text(
    text: str,
    source: str,
    target: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> str:
    """Переводит сплошной текст по кускам, сохраняя разбивку на строки."""
    if source == target or not text.strip():
        return text
    translator = GoogleTranslator(source=_google_code(source), target=_google_code(target))
    chunks = split_into_chunks(text)
    progress = on_progress or (lambda _i, _n: None)
    translated: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        translated.append(_with_retries(lambda c=chunk: translator.translate(c)))
        progress(index, len(chunks))
    return "\n".join(translated)


def _parse_marked(raw: str) -> dict[int, str]:
    """Достаёт из ответа переводчика реплики, помеченные как [[номер]]."""
    parts = _MARKER_RE.split(raw)
    parsed: dict[int, str] = {}
    for i in range(1, len(parts) - 1, 2):
        try:
            index = int(parts[i])
        except ValueError:
            continue
        parsed[index] = parts[i + 1].strip()
    return parsed


def translate_segments(
    segments: Sequence[Segment],
    source: str,
    target: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> list[str]:
    """Переводит реплики для субтитров: батчами с маркерами, fallback по одной."""
    if source == target:
        return [s.text for s in segments]
    translator = GoogleTranslator(source=_google_code(source), target=_google_code(target))
    progress = on_progress or (lambda _i, _n: None)
    result: list[str] = [""] * len(segments)
    done = 0

    def flush_batch(batch: list[tuple[int, str]]) -> None:
        nonlocal done
        joined = "\n".join(f"[[{idx}]] {text}" for idx, text in batch)
        try:
            raw = _with_retries(lambda: translator.translate(joined), "перевести субтитры")
            parsed = _parse_marked(raw)
        except TranslationError:
            parsed = {}
        for idx, text in batch:
            result[idx] = parsed.get(idx) or _with_retries(
                lambda t=text: translator.translate(t), "перевести реплику"
            )
            done += 1
            progress(done, len(segments))

    batch: list[tuple[int, str]] = []
    chars = 0
    for index, segment in enumerate(segments):
        if not segment.text.strip():
            result[index] = ""
            done += 1
            progress(done, len(segments))
            continue
        if batch and (chars + len(segment.text) > SEGMENT_BATCH_CHARS
                      or len(batch) >= SEGMENT_BATCH_MAX):
            flush_batch(batch)
            batch, chars = [], 0
        batch.append((index, segment.text.strip()))
        chars += len(segment.text) + 8
    if batch:
        flush_batch(batch)
    return result
