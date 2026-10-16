"""Скачивание аудиодорожки через yt-dlp.

yt-dlp поддерживает 1000+ площадок: YouTube (в т.ч. Shorts), Instagram,
TikTok, X/Twitter, VK, Rutube, Facebook, Reddit, Vimeo, Twitch и другие.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

_PLATFORMS = {
    "youtube": "YouTube",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "twitter": "X / Twitter",
    "facebook": "Facebook",
    "vimeo": "Vimeo",
    "reddit": "Reddit",
    "twitch": "Twitch",
    "vk": "VK",
    "rutube": "Rutube",
    "dailymotion": "Dailymotion",
    "soundcloud": "SoundCloud",
    "odysee": "Odysee",
    "bilibili": "Bilibili",
    "pinterest": "Pinterest",
    "linkedin": "LinkedIn",
    "telegram": "Telegram",
}


class DownloadError(Exception):
    """Понятная человеку ошибка скачивания."""


@dataclass
class VideoInfo:
    url: str
    title: str
    duration: float  # секунды (0, если неизвестно)
    uploader: str
    platform: str


def _platform_name(info: dict, webpage_url: str) -> str:
    extractor = str(info.get("extractor_key") or info.get("extractor") or "").lower()
    for key, name in _PLATFORMS.items():
        if extractor.startswith(key):
            if key == "youtube" and "/shorts/" in webpage_url:
                return "YouTube Shorts"
            return name
    return extractor.capitalize() if extractor else "Видео"


def _friendly_error(raw: str) -> str:
    message = _ANSI_RE.sub("", raw)
    if "ERROR:" in message:
        message = message.split("ERROR:", 1)[-1].strip()
    low = message.lower()
    if "unsupported url" in low:
        return "Этот сайт или ссылка не поддерживаются."
    if any(s in low for s in ("sign in", "login", "cookies", "private", "members-only",
                              "age-restricted", "age restricted")):
        return ("Видео приватное или требует входа. Попробуйте запустить с флагом "
                "--cookies-from-browser chrome (также доступны edge, firefox, brave).")
    if "unavailable" in low or "removed" in low:
        return "Видео недоступно: удалено, скрыто или ограничено автором."
    if any(s in low for s in ("timed out", "timeout", "connection", "network", "ssl")):
        return "Проблема с сетью — проверьте подключение к интернету."
    return f"Не удалось скачать видео: {message[:300]}"


def _base_opts(cookies_from_browser: Optional[str]) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "playlist_items": "1",
        "socket_timeout": 30,
        "retries": 3,
    }
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    return opts


def fetch_info(url: str, cookies_from_browser: Optional[str] = None) -> VideoInfo:
    """Метаданные видео: название, длительность, площадка."""
    opts = _base_opts(cookies_from_browser)
    opts["skip_download"] = True
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(_friendly_error(str(exc))) from exc
    except Exception as exc:  # noqa: BLE001 — yt-dlp умеет кидать разное
        raise DownloadError(f"Не удалось получить информацию о видео: {exc}") from exc

    if not info:
        raise DownloadError("Не удалось получить информацию о видео.")
    if info.get("entries"):  # плейлист → берём первое видео
        info = info["entries"][0]

    webpage = str(info.get("webpage_url") or url)
    return VideoInfo(
        url=webpage,
        title=str(info.get("title") or "Без названия").strip(),
        duration=float(info.get("duration") or 0),
        uploader=str(info.get("uploader") or info.get("channel") or "").strip(),
        platform=_platform_name(info, webpage),
    )


def download_audio(
    url: str,
    dest_dir: Path,
    on_progress: Callable[[int, int, float], None],
    cookies_from_browser: Optional[str] = None,
) -> Path:
    """Скачивает лучшую аудиодорожку во временную папку, возвращает путь к файлу."""

    def hook(data: dict) -> None:
        if data.get("status") == "downloading":
            total = int(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
            done = int(data.get("downloaded_bytes") or 0)
            speed = float(data.get("speed") or 0)
            on_progress(done, total, speed)

    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = _base_opts(cookies_from_browser)
    opts.update(
        {
            "format": "bestaudio/best",
            "outtmpl": str(dest_dir / "audio.%(ext)s"),
            "progress_hooks": [hook],
            "overwrites": True,
        }
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(_friendly_error(str(exc))) from exc

    if info and info.get("entries"):
        info = info["entries"][0]

    for entry in (info or {}).get("requested_downloads") or []:
        candidate = entry.get("filepath")
        if candidate and Path(candidate).exists():
            return Path(candidate)

    files = sorted(dest_dir.glob("audio.*"), key=lambda p: p.stat().st_mtime)
    if files:
        return files[-1]
    raise DownloadError("Не удалось найти скачанный аудиофайл.")
