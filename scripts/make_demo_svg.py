"""Генерирует docs/demo.svg — демонстрацию работы для README.

Запуск: uv run python scripts/make_demo_svg.py
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from transcriber import __version__, ui
from transcriber.downloader import VideoInfo

DEMO_TEXT = (
    "Хорошо, вот мы и оказались перед слонами.\n"
    "Самое классное в этих парнях — у них очень, очень, очень длинные хоботы.\n"
    "И это круто.\n"
    "И это почти всё, что можно сказать."
)


def main() -> None:
    console = Console(record=True, width=100, force_terminal=True, color_system="truecolor")
    original = ui.console
    ui.console = console
    try:
        ui.banner("turbo", "RU", __version__)
        console.print()
        ui.prompt_box("https://www.youtube.com/watch?v=jNQXAC9IVRw")
        console.print()
        ui.video_card(
            VideoInfo(
                url="https://www.youtube.com/watch?v=jNQXAC9IVRw",
                title="Me at the zoo",
                duration=19.0,
                uploader="jawed",
                platform="YouTube",
            )
        )
        ui.info("Язык видео: английский — перевожу на русский…")
        ui.show_result(
            "Me at the zoo",
            DEMO_TEXT,
            "YouTube · английский · 4 реплики · 36 слов",
        )
        ui.menu_line(
            [
                ("c", "копировать"),
                ("s", "сохранить .txt"),
                ("r", "сохранить .srt"),
                ("n", "новое видео"),
                ("q", "выход"),
            ]
        )
        console.print(f"{ui.INDENT}[dim]Клавиша и Enter — или сразу вставьте новую ссылку.[/]")
    finally:
        ui.console = original

    svg = console.export_svg(title="transcriber — транскрибация видео прямо в консоли")
    output = Path(__file__).resolve().parents[1] / "docs" / "demo.svg"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8")
    print(f"готово: {output} ({output.stat().st_size} байт)")


if __name__ == "__main__":
    main()
