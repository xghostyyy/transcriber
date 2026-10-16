"""Скачивание аудиодорожки через yt-dlp.

yt-dlp поддерживает 1000+ площадок: YouTube (в т.ч. Shorts), Instagram,
TikTok, X/Twitter, VK, Rutube, Facebook, Reddit, Vimeo, Twitch и другие.

Если основной способ скачивания не сработал, пробуем запасные: другой
клиент YouTube при HTTP 403, cookies из установленных браузеров при
проверке «войдите, чтобы продолжить». При сетевых обрывах повторяем
запрос и объясняем, что может помочь VPN или --proxy.
"""

from __future__ import annotations

import os
import re
import time
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

# клиенты YouTube, которые пробуем при HTTP 403 или проверке на бота
_YT_PLAYER_CLIENTS = ("android_vr", "tv", "web_safari", "ios", "mweb")

# сетевые сбои — имеет смысл просто повторить запрос
_NETWORK_MARKERS = (
    "connection reset",
    "connection aborted",
    "connection refused",
    "forcibly closed",
    "10054",
    "10061",
    "timed out",
    "timeout",
    "eof occurred",
    "ssl",
    "network",
    "proxy",
    "temporarily unavailable",
    "http error 5",
    "unable to download webpage",
)

# ошибки, при которых могут помочь фолбэки (другой клиент / cookies)
_FALLBACK_MARKERS = (
    "403",
    "forbidden",
    "sign in",
    "login",
    "bot",
    "age",
    "cookie",
    "could not copy",
    "private",
    "members-only",
    "unable to extract",
    "no video formats",
    "requested format",
    "decrypt",
)

# безнадёжные случаи — фолбэки не помогут, падаем сразу
_FATAL_MARKERS = (
    "unsupported url",
    "video unavailable",
    "has been removed",
    "no longer available",
    "deleted",
    "terminated",
    "copyright",
    "in your country",
    "geo-restricted",
    "geo restricted",
    "not available from your location",
)


class DownloadError(Exception):
    """Понятная человеку ошибка скачивания."""


@dataclass
class VideoInfo:
    url: str
    title: str
    duration: float  # секунды (0, если неизвестно)
    uploader: str
    platform: str


class _QuietLogger:
    """Молчащий логгер для yt-dlp.

    Параметр quiet не глушит сообщения об ошибках в stderr — их пишет
    to_stderr(), а он уважает только logger. Ошибки показываем сами,
    по-русски и без дублей.
    """

    def debug(self, message: str) -> None:
        pass

    def info(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass


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
    if any(
        s in low
        for s in ("in your country", "geo-restricted", "geo restricted",
                  "not available from your location")
    ):
        return (
            "Видео заблокировано в вашем регионе. Включите VPN "
            "или укажите прокси: --proxy socks5://127.0.0.1:1080"
        )
    if any(s in low for s in ("sign in", "login", "cookies", "private", "members-only",
                              "age-restricted", "age restricted", "bot")):
        return ("Видео приватное или требует входа. Попробуйте запустить с флагом "
                "--cookies-from-browser chrome (также доступны edge, firefox, brave).")
    if "unavailable" in low or "removed" in low:
        return "Видео недоступно: удалено, скрыто или ограничено автором."
    if any(
        s in low
        for s in ("connection reset", "connection aborted", "forcibly closed",
                  "connection refused", "10054", "10061", "eof occurred")
    ):
        return (
            "Соединение с сайтом разорвано — похоже на блокировку у провайдера "
            "или сбой сети. Попробуйте ещё раз, включите/выключите VPN "
            "или укажите прокси: --proxy socks5://127.0.0.1:1080"
        )
    if any(s in low for s in ("timed out", "timeout", "connection", "network", "ssl")):
        return "Проблема с сетью — проверьте подключение к интернету."
    return f"Не удалось скачать видео: {message[:300]}"


def _has_fatal(raw_low: str) -> bool:
    return any(marker in raw_low for marker in _FATAL_MARKERS)


def _is_hopeless_http(raw_low: str) -> bool:
    """HTTP 4xx (кроме 403 — он лечится сменой клиента) повторять бессмысленно."""
    match = re.search(r"http error (4\d\d)", raw_low)
    return bool(match) and match.group(1) != "403"


def _is_network_error(raw: str) -> bool:
    low = _ANSI_RE.sub("", raw).lower()
    if _has_fatal(low) or _is_hopeless_http(low):
        return False
    return any(marker in low for marker in _NETWORK_MARKERS)


def _should_retry(raw: str) -> bool:
    """Стоит ли пробовать ещё: сеть мигнула, либо помогут фолбэки."""
    low = _ANSI_RE.sub("", raw).lower()
    if _has_fatal(low) or _is_hopeless_http(low):
        return False
    return any(marker in low for marker in _NETWORK_MARKERS + _FALLBACK_MARKERS)


def _is_youtube(url: str) -> bool:
    low = url.lower()
    return "youtube.com" in low or "youtu.be" in low


def _env_path(name: str) -> Optional[Path]:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else None


def _browser_dirs() -> dict[str, tuple[Optional[Path], ...]]:
    """Где на этой системе могут лежать профили браузеров с cookies."""
    home = Path.home()
    local = _env_path("LOCALAPPDATA")      # Windows
    roaming = _env_path("APPDATA")         # Windows
    return {
        "chrome": (
            local / "Google" / "Chrome" / "User Data" if local else None,
            home / ".config" / "google-chrome",
            home / "Library" / "Application Support" / "Google" / "Chrome",
        ),
        "edge": (
            local / "Microsoft" / "Edge" / "User Data" if local else None,
            home / ".config" / "microsoft-edge",
            home / "Library" / "Application Support" / "Microsoft Edge",
        ),
        "firefox": (
            roaming / "Mozilla" / "Firefox" / "Profiles" if roaming else None,
            home / ".mozilla" / "firefox",
            home / "Library" / "Application Support" / "Firefox" / "Profiles",
        ),
        "brave": (
            local / "BraveSoftware" / "Brave-Browser" / "User Data" if local else None,
            home / ".config" / "BraveSoftware" / "Brave-Browser",
            home / "Library" / "Application Support" / "BraveSoftware" / "Brave-Browser",
        ),
    }


def _available_browsers() -> list[str]:
    """Браузеры, профили которых есть на диске — из них есть смысл брать cookies."""
    available = []
    for browser, candidates in _browser_dirs().items():
        if any(path is not None and path.is_dir() for path in candidates):
            available.append(browser)
    return available


def _fallbacks(url: str, base_opts: dict) -> list[tuple[str, dict]]:
    """Запасные способы скачивания к уже применённым настройкам."""
    if base_opts.get("cookiesfrombrowser"):
        return []  # браузер указан явно — чужие cookies не подставляем
    chain: list[tuple[str, dict]] = []
    if _is_youtube(url):
        for client in _YT_PLAYER_CLIENTS:
            chain.append((
                f"пробую клиент YouTube «{client}»",
                {"extractor_args": {"youtube": {"player_client": [client]}}},
            ))
    for browser in _available_browsers():
        chain.append((f"пробую cookies из {browser}", {"cookiesfrombrowser": (browser,)}))
    return chain


def _base_opts(
    cookies_from_browser: Optional[str] = None, proxy: Optional[str] = None
) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "playlist_items": "1",
        "socket_timeout": 30,
        "retries": 3,
        "logger": _QuietLogger(),
    }
    if proxy:
        opts["proxy"] = proxy
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    return opts


def _try_extract(url: str, opts: dict, download: bool) -> tuple[Optional[dict], str]:
    """Одна попытка extract_info; возвращает (info, "") или (None, сырая ошибка)."""
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=download), ""
    except yt_dlp.utils.DownloadError as exc:
        return None, str(exc)


def _extract(
    url: str,
    base_opts: dict,
    download: bool,
    on_retry: Optional[Callable[[str], None]],
) -> dict:
    """extract_info с повтором при сетевых сбоях и запасными способами."""
    notify = on_retry or (lambda _message: None)

    info, first_raw = _try_extract(url, base_opts, download)
    if info is not None:
        return info

    if _is_network_error(first_raw):
        notify("Соединение сорвалось — пробую ещё раз…")
        time.sleep(1.0)
        info, _raw = _try_extract(url, base_opts, download)
        if info is not None:
            return info

    if _should_retry(first_raw):
        for label, patch in _fallbacks(url, base_opts):
            notify(f"Основной способ не сработал — {label}…")
            info, raw = _try_extract(url, {**base_opts, **patch}, download)
            if info is not None:
                return info
            if not _should_retry(raw):
                break

    raise DownloadError(_friendly_error(first_raw))


def fetch_info(
    url: str,
    cookies_from_browser: Optional[str] = None,
    proxy: Optional[str] = None,
    on_retry: Optional[Callable[[str], None]] = None,
) -> VideoInfo:
    """Метаданные видео: название, длительность, площадка."""
    opts = _base_opts(cookies_from_browser, proxy)
    opts["skip_download"] = True
    try:
        info = _extract(url, opts, download=False, on_retry=on_retry)
    except DownloadError:
        raise
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
    proxy: Optional[str] = None,
    on_retry: Optional[Callable[[str], None]] = None,
) -> Path:
    """Скачивает лучшую аудиодорожку во временную папку, возвращает путь к файлу."""

    def hook(data: dict) -> None:
        if data.get("status") == "downloading":
            total = int(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
            done = int(data.get("downloaded_bytes") or 0)
            speed = float(data.get("speed") or 0)
            on_progress(done, total, speed)

    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = _base_opts(cookies_from_browser, proxy)
    opts.update(
        {
            "format": "bestaudio/best",
            "outtmpl": str(dest_dir / "audio.%(ext)s"),
            "progress_hooks": [hook],
            "overwrites": True,
        }
    )
    try:
        info = _extract(url, opts, download=True, on_retry=on_retry)
    except DownloadError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DownloadError(f"Не удалось скачать видео: {exc}") from exc

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
