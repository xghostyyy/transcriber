"""Сохранение результатов: буфер обмена, .txt, .srt."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Sequence

from .transcriber import Segment

_BAD_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def slugify(title: str, limit: int = 80) -> str:
    """Превращает название видео в безопасное имя файла."""
    slug = _BAD_FILENAME_CHARS.sub("", title).strip().rstrip(". ")
    slug = re.sub(r"\s+", " ", slug)
    if len(slug) > limit:
        slug = slug[:limit].rstrip()
    return slug or "транскрипция"


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}{suffix}"
    counter = 2
    while path.exists():
        path = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return path


def save_txt(text: str, title: str, directory: Path) -> Path:
    path = unique_path(directory, slugify(title), ".txt")
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def format_timestamp(seconds: float) -> str:
    """Секунды → формат SRT: 00:01:23,456."""
    total_ms = max(0, int(round(seconds * 1000)))
    hours, total_ms = divmod(total_ms, 3_600_000)
    minutes, total_ms = divmod(total_ms, 60_000)
    secs, millis = divmod(total_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_srt(segments: Sequence[Segment], texts: Optional[Sequence[str]] = None) -> str:
    lines: list[str] = []
    number = 0
    for index, segment in enumerate(segments):
        text = (texts[index] if texts is not None else segment.text).strip()
        if not text:
            continue
        number += 1
        lines.append(str(number))
        lines.append(f"{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def save_srt(
    segments: Sequence[Segment],
    title: str,
    directory: Path,
    texts: Optional[Sequence[str]] = None,
) -> Path:
    path = unique_path(directory, slugify(title), ".srt")
    path.write_text(format_srt(segments, texts), encoding="utf-8")
    return path


def copy_to_clipboard(text: str) -> bool:
    try:
        import pyperclip

        pyperclip.copy(text)
        return True
    except Exception:  # noqa: BLE001 — в некоторых окружениях буфера нет
        return False
