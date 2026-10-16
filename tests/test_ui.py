"""Тесты интерфейса: чат-бокс для ввода и выравнивание рамки."""

import io

from rich.console import Console

from transcriber import ui


def test_prompt_box_lines_are_aligned():
    buffer = io.StringIO()
    original = ui.console
    ui.console = Console(file=buffer, width=60)
    try:
        ui.prompt_box("https://example.com/video")
    finally:
        ui.console = original

    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    assert lines[0].strip().startswith("╭")
    assert "❯ https://example.com/video" in lines[1]
    assert lines[-1].strip().startswith("╰")
    # все три строки рамки одинаковой ширины: отступ 2 + бокс 56
    assert {len(line) for line in lines} == {58}


def test_read_menu_returns_key_and_full_line(monkeypatch):
    # строку с точкой меню отдаёт целиком — её распознаёт cli как ссылку
    monkeypatch.setattr(ui, "_plain_ask", lambda: "ссылка.рф")
    assert ui.read_menu() == ("c", "ссылка.рф")


def test_read_menu_understands_russian_layout(monkeypatch):
    monkeypatch.setattr(ui, "_plain_ask", lambda: "Копировать")
    assert ui.read_key() == "r"
    monkeypatch.setattr(ui, "_plain_ask", lambda: "")
    assert ui.read_key() == ""


def test_read_menu_survives_eof(monkeypatch):
    def raise_eof() -> str:
        raise EOFError

    monkeypatch.setattr(ui, "_plain_ask", raise_eof)
    assert ui.read_menu() == ("q", "q")


def test_ask_draws_frame_and_repositions_cursor(monkeypatch):
    buffer = io.StringIO()
    original = ui.console
    ui.console = Console(file=buffer, width=60)
    out = io.StringIO()
    monkeypatch.setattr(ui, "_box_supported", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "привет")
    monkeypatch.setattr(ui.sys, "stdout", out)
    try:
        answer = ui.ask()
    finally:
        ui.console = original

    assert answer == "привет"
    printed = buffer.getvalue()
    assert "╭" in printed and "❯" in printed and "╰" in printed
    # курсор поднимается на строку вверх и встаёт на правую границу (2 + 56 - 1)
    assert out.getvalue() == "\x1b[1A\x1b[57C│\n"


def test_ask_closes_frame_on_eof(monkeypatch):
    buffer = io.StringIO()
    original = ui.console
    ui.console = Console(file=buffer, width=60)
    monkeypatch.setattr(ui, "_box_supported", lambda: True)

    def raise_eof() -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    try:
        try:
            ui.ask()
        except EOFError:
            pass
        else:  # pragma: no cover — сюда попадать не должны
            raise AssertionError("ask() должен пробросить EOFError")
    finally:
        ui.console = original

    assert "╰" in buffer.getvalue()
