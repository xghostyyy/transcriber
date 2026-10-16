"""Тесты истории расшифровок: сохранение, чтение, чистка."""

import time

import transcriber.history as history
from transcriber.transcriber import Segment, TranscriptResult


def make_result() -> TranscriptResult:
    return TranscriptResult(
        segments=[Segment(0, 1, "Привет"), Segment(1, 2, "Мир")],
        language="ru",
        language_probability=0.9,
        duration=2.0,
    )


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path)
    entry = history.save_entry(
        title="Тестовое видео",
        url="https://example.com/video",
        platform="YouTube",
        model="small",
        result=make_result(),
        output_text="Hello\nWorld",
        output_language="en",
        max_entries=10,
    )
    assert entry.translated is True

    loaded = history.load_entries()
    assert len(loaded) == 1
    assert loaded[0].title == "Тестовое видео"
    assert loaded[0].text == "Hello\nWorld"
    assert [s.text for s in loaded[0].segments] == ["Привет", "Мир"]
    assert loaded[0].translated is True


def test_not_translated_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path)
    entry = history.save_entry(
        title="Оригинал",
        url="",
        platform="",
        model="tiny",
        result=make_result(),
        output_text="Привет\nМир",
        output_language="ru",
    )
    assert entry.translated is False


def test_prune_keeps_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path)
    for index in range(5):
        history.save_entry(
            title=f"Видео {index}",
            url="",
            platform="",
            model="tiny",
            result=make_result(),
            output_text="x",
            output_language="ru",
            max_entries=3,
        )
        time.sleep(0.02)

    loaded = history.load_entries()
    assert len(loaded) == 3
    assert loaded[0].title == "Видео 4"
    assert loaded[-1].title == "Видео 2"


def test_load_entries_of_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "нет-такой-папки")
    assert history.load_entries() == []


def test_broken_file_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path)
    (tmp_path / "broken.json").write_text("{не json", encoding="utf-8")
    assert history.load_entries() == []
