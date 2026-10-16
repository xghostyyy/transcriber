"""Тесты экспорта: имена файлов, таймкоды, SRT."""

from transcriber.output import format_srt, format_timestamp, slugify, unique_path
from transcriber.transcriber import Segment


def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(1.5) == "00:00:01,500"
    assert format_timestamp(3725.456) == "01:02:05,456"
    assert format_timestamp(-5) == "00:00:00,000"


def test_format_srt_skips_empty_segments():
    segments = [Segment(0, 1, "Привет"), Segment(1, 2, "   "), Segment(2, 3, "Пока")]
    srt = format_srt(segments)
    assert srt.count("-->") == 2
    assert "1\n00:00:00,000 --> 00:00:01,000\nПривет" in srt
    assert "2\n00:00:02,000 --> 00:00:03,000\nПока" in srt


def test_format_srt_uses_translated_texts():
    segments = [Segment(0, 1, "Hello"), Segment(1, 2, "Bye")]
    srt = format_srt(segments, texts=["Привет", "Пока"])
    assert "Привет" in srt and "Пока" in srt
    assert "Hello" not in srt


def test_slugify_strips_forbidden_chars():
    slug = slugify('Видео: "тест" <чат> / 100%?')
    for bad in '<>:"/\\|?*':
        assert bad not in slug
    assert slug


def test_slugify_fallback_for_empty_result():
    assert slugify("???") == "транскрипция"


def test_unique_path_adds_suffix(tmp_path):
    first = unique_path(tmp_path, "имя", ".txt")
    first.write_text("x", encoding="utf-8")
    second = unique_path(tmp_path, "имя", ".txt")
    assert first.name == "имя.txt"
    assert second.name == "имя-2.txt"
