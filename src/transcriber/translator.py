"""Перевод текста через публичный эндпоинт Google (бесплатно, без ключей).

Используется endpoint translate_a/single — он стабильнее веб-эндпоинта
translate.google.com/m и практически не ограничивает частоту запросов.
"""

from __future__ import annotations

import re
import time
from typing import Callable, Optional, Sequence

import requests

from .transcriber import Segment

MAX_CHUNK_CHARS = 4000      # консервативный лимит Google
SEGMENT_BATCH_CHARS = 3200  # размер батча при переводе субтитров
SEGMENT_BATCH_MAX = 30      # максимум реплик в одном батче

_GTX_URL = "https://translate.googleapis.com/translate_a/single"
_CLIENTS5_URL = "https://clients5.google.com/translate_a/t"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_CODE_MAP = {"he": "iw", "zh": "zh-CN", "jv": "jw"}
_MARKER_RE = re.compile(r"\[\[\s*(\d+)\s*\]\]")


class TranslationError(Exception):
    """Понятная человеку ошибка перевода."""


def _google_code(code: str) -> str:
    return _CODE_MAP.get(code, code)


def _request(url: str, params: dict) -> requests.Response:
    try:
        response = requests.get(url, params=params, headers=_HEADERS, timeout=30)
    except requests.RequestException as exc:
        raise TranslationError(f"сеть недоступна ({exc.__class__.__name__})") from exc
    if response.status_code == 429:
        raise TranslationError("Google временно ограничил частоту переводов (429)")
    if response.status_code != 200:
        raise TranslationError(f"Google ответил кодом {response.status_code}")
    return response


def _via_gtx(text: str, source: str, target: str) -> str:
    """Основной эндпоинт translate_a/single."""
    response = _request(
        _GTX_URL,
        {
            "client": "gtx",
            "sl": _google_code(source or "auto"),
            "tl": _google_code(target),
            "dt": "t",
            "q": text,
        },
    )
    try:
        data = response.json()
        translated = "".join(part[0] for part in (data[0] or []) if part and part[0])
    except (ValueError, TypeError, IndexError) as exc:
        raise TranslationError("не удалось разобрать ответ") from exc
    if not translated.strip():
        raise TranslationError("пустой ответ")
    return translated


def _via_clients5(text: str, source: str, target: str) -> str:
    """Запасной эндпоинт clients5 — помогает, когда основной залимичен."""
    response = _request(
        _CLIENTS5_URL,
        {
            "client": "dict-chrome-ex",
            "sl": _google_code(source or "auto"),
            "tl": _google_code(target),
            "q": text,
        },
    )
    try:
        data = response.json()
        if isinstance(data, list):
            translated = "".join(str(item) for item in data)
        elif isinstance(data, str):
            translated = data
        else:
            raise TranslationError("неожиданный формат ответа")
    except ValueError as exc:
        raise TranslationError("не удалось разобрать ответ") from exc
    if not translated.strip():
        raise TranslationError("пустой ответ")
    return translated


def _google_translate(text: str, source: str, target: str) -> str:
    """Пробует оба эндпоинта по очереди и возвращает первый успешный результат."""
    errors: list[str] = []
    for backend in (_via_gtx, _via_clients5):
        try:
            return backend(text, source, target)
        except TranslationError as exc:
            errors.append(str(exc))
    raise TranslationError(f"перевод не удался ({'; '.join(errors)})")


def _with_retries(func: Callable[[], str], what: str = "перевести текст") -> str:
    last: Optional[Exception] = None
    for attempt in range(4):
        try:
            return func()
        except TranslationError as exc:
            last = exc
            time.sleep(2.0 * (attempt + 1))
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
    chunks = split_into_chunks(text)
    progress = on_progress or (lambda _i, _n: None)
    translated: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        translated.append(_with_retries(lambda c=chunk: _google_translate(c, source, target)))
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
    progress = on_progress or (lambda _i, _n: None)
    result: list[str] = [""] * len(segments)
    done = 0

    def flush_batch(batch: list[tuple[int, str]]) -> None:
        nonlocal done
        joined = "\n".join(f"[[{idx}]] {text}" for idx, text in batch)
        try:
            raw = _with_retries(
                lambda: _google_translate(joined, source, target), "перевести субтитры"
            )
            parsed = _parse_marked(raw)
        except TranslationError:
            parsed = {}
        for idx, text in batch:
            result[idx] = parsed.get(idx) or _with_retries(
                lambda t=text: _google_translate(t, source, target), "перевести реплику"
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
