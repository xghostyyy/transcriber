"""Тесты перевода: нарезка текста, маркеры, фолбэк эндпоинтов."""

import pytest

from transcriber import translator
from transcriber.transcriber import Segment
from transcriber.translator import (
    TranslationError,
    _parse_marked,
    split_into_chunks,
    translate_segments,
    translate_text,
)


def test_split_respects_limit():
    text = "\n".join(["Короткая строка номер раз."] * 200)
    chunks = split_into_chunks(text, limit=400)
    assert chunks
    assert all(len(chunk) <= 400 for chunk in chunks)


def test_split_keeps_all_words():
    text = "Первое предложение. " * 300
    chunks = split_into_chunks(text, limit=500)
    assert " ".join(chunks).split() == text.split()


def test_split_hard_breaks_word_longer_than_limit():
    text = "б" * 9000
    chunks = split_into_chunks(text, limit=4000)
    assert all(len(chunk) <= 4000 for chunk in chunks)
    assert "".join(chunks) == text


def test_parse_marked():
    parsed = _parse_marked("[[0]] Привет\n[[1]] Пока\n[[2]] Конец")
    assert parsed == {0: "Привет", 1: "Пока", 2: "Конец"}


def test_translate_text_uses_backend(monkeypatch):
    monkeypatch.setattr(
        translator, "_google_translate", lambda text, src, tgt: f"<{tgt}>{text}"
    )
    assert translate_text("Привет", "ru", "en") == "<en>Привет"


def test_same_language_skips_translation(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("переводчик не должен вызываться")

    monkeypatch.setattr(translator, "_google_translate", boom)
    assert translate_text("Привет", "ru", "ru") == "Привет"


def test_translate_segments_falls_back_per_segment(monkeypatch):
    def fake(text, _src, tgt):
        if "[[" in text:  # маркеры «сломались» — батч не разобрать
            return "без маркеров"
        return f"<{tgt}>{text}"

    monkeypatch.setattr(translator, "_google_translate", fake)
    segments = [Segment(0, 1, "Один"), Segment(1, 2, ""), Segment(2, 3, "Два")]
    out = translate_segments(segments, "ru", "en")
    assert out == ["<en>Один", "", "<en>Два"]


def test_google_translate_falls_back_to_clients5(monkeypatch):
    def make(name):
        def impl(_text, _src, _tgt):
            if name == "gtx":
                raise TranslationError("429")
            return "ok"

        return impl

    monkeypatch.setattr(translator, "_via_gtx", make("gtx"))
    monkeypatch.setattr(translator, "_via_clients5", make("clients5"))
    assert translator._google_translate("текст", "ru", "en") == "ok"


def test_google_translate_reports_both_backends(monkeypatch):
    def fail(*_args, **_kwargs):
        raise TranslationError("нет связи")

    monkeypatch.setattr(translator, "_via_gtx", fail)
    monkeypatch.setattr(translator, "_via_clients5", fail)
    with pytest.raises(TranslationError, match="нет связи"):
        translator._google_translate("текст", "ru", "en")
