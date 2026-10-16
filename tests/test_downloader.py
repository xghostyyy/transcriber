"""Тесты скачивателя: понятные ошибки, площадки, повторы и фолбэки."""

from transcriber import downloader
from transcriber.downloader import (
    _available_browsers,
    _base_opts,
    _fallbacks,
    _friendly_error,
    _platform_name,
    _should_retry,
)


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


def test_friendly_error_connection_reset_suggests_vpn():
    raw = (
        "ERROR: [vm.tiktok] ZSgFV573E: Unable to download webpage: "
        "('Connection aborted.', ConnectionResetError(10054, '...'))"
    )
    message = _friendly_error(raw)
    assert "VPN" in message
    assert "--proxy" in message


def test_friendly_error_geo_suggests_vpn():
    message = _friendly_error(
        "ERROR: The uploader has not made this video available in your country"
    )
    assert "VPN" in message


def test_friendly_error_strips_ansi_and_prefix():
    raw = "\x1b[0;31mERROR: Something bad\x1b[0m"
    message = _friendly_error(raw)
    assert "\x1b" not in message
    assert "ERROR:" not in message


def test_should_retry_connection_reset():
    raw = "Unable to download webpage: ConnectionResetError(10054, '...')"
    assert _should_retry(raw) is True


def test_should_retry_bot_check_needs_cookies():
    assert _should_retry("ERROR: Sign in to confirm you're not a bot") is True
    assert _should_retry("ERROR: Could not copy Chrome cookie database") is True


def test_should_retry_skips_hopeless_cases():
    assert _should_retry("ERROR: Video unavailable") is False
    assert _should_retry("ERROR: Unsupported URL: https://x") is False
    assert _should_retry("ERROR: HTTP Error 404: Not Found") is False
    assert _should_retry("ERROR: This video is not available in your country") is False


def test_base_opts_sets_proxy_and_quiet_logger():
    opts = _base_opts(None, "socks5://127.0.0.1:1080")
    assert opts["proxy"] == "socks5://127.0.0.1:1080"
    assert opts["logger"] is not None
    assert "proxy" not in _base_opts(None)


def test_fallbacks_empty_with_explicit_browser():
    opts = {"cookiesfrombrowser": ("chrome",)}
    assert _fallbacks("https://youtube.com/watch?v=1", opts) == []


def test_fallbacks_include_youtube_clients(monkeypatch):
    monkeypatch.setattr(downloader, "_available_browsers", list)
    chain = _fallbacks("https://youtu.be/abc", {})
    patches = [patch for _label, patch in chain]
    assert any("player_client" in str(patch) for patch in patches)
    # для не-YouTube клиенты не подставляем
    assert _fallbacks("https://vm.tiktok.com/x", {}) == []


def test_fallbacks_include_available_browsers(monkeypatch):
    monkeypatch.setattr(downloader, "_available_browsers", lambda: ["firefox"])
    chain = _fallbacks("https://vm.tiktok.com/x", {})
    assert chain == [("пробую cookies из firefox", {"cookiesfrombrowser": ("firefox",)})]


def test_available_browsers_detects_existing_profiles(monkeypatch, tmp_path):
    missing = tmp_path / "нет-такого"
    profile = tmp_path / "профиль"
    profile.mkdir()
    monkeypatch.setattr(
        downloader,
        "_browser_dirs",
        lambda: {"chrome": (missing, None), "firefox": (profile,)},
    )
    assert _available_browsers() == ["firefox"]


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
