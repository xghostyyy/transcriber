"""История расшифровок: json-файлы в ~/.config/transcriber/history."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import HISTORY_DIR
from .output import slugify
from .transcriber import Segment, TranscriptResult


@dataclass
class HistoryEntry:
    path: Path
    title: str
    url: str
    platform: str
    duration: float
    model: str
    detected_language: str
    output_language: str
    created: float            # unix-время
    text: str                 # итоговый текст (возможно переведённый)
    segments: list[Segment]   # сегменты на языке оригинала

    @property
    def translated(self) -> bool:
        return self.output_language != self.detected_language

    @property
    def created_str(self) -> str:
        return time.strftime("%d.%m.%Y %H:%M", time.localtime(self.created))


def save_entry(
    *,
    title: str,
    url: str,
    platform: str,
    model: str,
    result: TranscriptResult,
    output_text: str,
    output_language: str,
    max_entries: int = 100,
) -> HistoryEntry:
    """Сохраняет расшифровку в историю и подчищает старые записи."""
    created = time.time()
    data = {
        "created": created,
        "title": title,
        "url": url,
        "platform": platform,
        "duration": result.duration,
        "model": model,
        "detected_language": result.language,
        "output_language": output_language,
        "text": output_text,
        "segments": [[round(s.start, 3), round(s.end, 3), s.text] for s in result.segments],
    }
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(created))
    stem = f"{stamp}-{slugify(title, 40)}"
    path = HISTORY_DIR / f"{stem}.json"
    counter = 2
    while path.exists():
        path = HISTORY_DIR / f"{stem}-{counter}.json"
        counter += 1
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    prune(max_entries)
    return HistoryEntry(
        path=path,
        title=title,
        url=url,
        platform=platform,
        duration=result.duration,
        model=model,
        detected_language=result.language,
        output_language=output_language,
        created=created,
        text=output_text,
        segments=list(result.segments),
    )


def load_entries(limit: Optional[int] = None) -> list[HistoryEntry]:
    """Свежие записи истории сверху."""
    if not HISTORY_DIR.exists():
        return []
    files = sorted(HISTORY_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    entries: list[HistoryEntry] = []
    for path in files:
        entry = _read(path)
        if entry is not None:
            entries.append(entry)
        if limit and len(entries) >= limit:
            break
    return entries


def prune(max_entries: int) -> None:
    files = sorted(HISTORY_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[max_entries:]:
        try:
            old.unlink()
        except OSError:
            pass


def _read(path: Path) -> Optional[HistoryEntry]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        segments = [
            Segment(float(item[0]), float(item[1]), str(item[2]))
            for item in data.get("segments", [])
        ]
        return HistoryEntry(
            path=path,
            title=str(data.get("title") or path.stem),
            url=str(data.get("url") or ""),
            platform=str(data.get("platform") or ""),
            duration=float(data.get("duration") or 0),
            model=str(data.get("model") or ""),
            detected_language=str(data.get("detected_language") or ""),
            output_language=str(data.get("output_language") or ""),
            created=float(data.get("created") or path.stat().st_mtime),
            text=str(data.get("text") or ""),
            segments=segments,
        )
    except Exception:  # noqa: BLE001 — битый файл просто пропускаем
        return None
