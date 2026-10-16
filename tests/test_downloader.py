"""Тесты скачивателя: понятные ошибки и название площадки."""

from transcriber.downloader import _friendly_error, _platform_name


def test_friendly_error_suggests_cookies():
    message = _friendly_error(
        "ERROR: [youtube] abc123: Sign in to confirm you're not a bot"
    )
    assert "--cookies-from-browser" in message


def test_friendly_error_unsupported_url():
    assert "не поддерживаются" in _friendly_error("ERROR: Unsupported URL: https://x")


def test_friendly_error_unavailable():
    assert "недоступно" in _friendly_error("ERROR: Video unavailable")


def test_friendly_error_network():
    assert "сеть" in _friendly_error("ERROR: The read operation timed out")


def test_friendly_error_strips_ansi_and_prefix():
    raw = "\x1b[0;31mERROR: Something bad\x1b[0m"
    message = _friendly_error(raw)
    assert "\x1b" not in message
    assert "ERROR:" not in message


def test_platform_name_youtube_shorts():
    assert (
        _platform_name({"extractor_key": "Youtube"}, "https://youtube.com/shorts/abc")
        == "YouTube Shorts"
    )


def test_platform_name_known():
    assert _platform_name({"extractor_key": "TikTok"}, "https://tiktok.com/x") == "TikTok"
    assert _platform_name({"extractor_key": "Instagram"}, "https://instagram.com/x") == "Instagram"


def test_platform_name_fallback():
    assert _platform_name({}, "https://example.com/video") == "Видео"
    assert _platform_name({"extractor_key": "SomeSite"}, "https://somesite.com") == "Somesite"
