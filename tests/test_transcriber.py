"""Тесты распознавания: имена языков, текст результата, выбор устройства."""

from transcriber import transcriber as transcriber_mod
from transcriber.transcriber import (
    Segment,
    TranscriptResult,
    _resolve_device,
    language_name,
    load_model,
)


def test_language_name_known():
    assert language_name("ru") == "русский"
    assert language_name("en") == "английский"


def test_language_name_unknown_falls_back_to_code():
    assert language_name("xx") == "xx"
    assert language_name("") == "неизвестен"


def test_result_text_joins_segments():
    result = TranscriptResult(
        segments=[Segment(0, 1, "Привет"), Segment(1, 2, ""), Segment(2, 3, "мир")],
        language="ru",
        language_probability=1.0,
        duration=3.0,
    )
    assert result.text == "Привет\nмир"
    assert result.word_count == 2


def test_resolve_device_explicit_choices():
    assert _resolve_device("cpu") == ("cpu", "int8")
    assert _resolve_device("cuda") == ("cuda", "int8_float16")


def test_resolve_device_auto_returns_valid_pair():
    device, compute = _resolve_device("auto")
    assert (device, compute) in {("cpu", "int8"), ("cuda", "int8_float16")}


def test_load_model_keeps_model_in_memory(monkeypatch):
    """Повторный вызов с той же моделью не должен пересобирать её с диска."""
    built: list[str] = []

    class FakeModel:
        def __init__(self, path: str, **kwargs) -> None:
            built.append(path)

    monkeypatch.setattr(transcriber_mod, "WhisperModel", FakeModel)
    monkeypatch.setattr(transcriber_mod, "_ensure_model", lambda name, status: f"путь/{name}")
    monkeypatch.setattr(transcriber_mod, "_resolve_device", lambda pref: ("cpu", "int8"))
    monkeypatch.setattr(transcriber_mod, "_MODEL_CACHE", {})

    first = load_model("turbo")
    second = load_model("turbo")
    assert first is second
    assert built == ["путь/turbo"]

    load_model("small")
    assert built == ["путь/turbo", "путь/small"]
