"""Консольный интерфейс на rich: баннер, прогресс-бары, панели результата.

Оформление в духе opencode: чат-блок для ввода, отступы по краям,
аккуратные прогресс-бары.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Callable, Iterator

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.padding import Padding
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text

from .downloader import VideoInfo

console = Console()
ACCENT = "cyan"
MARGIN = 2
INDENT = " " * MARGIN

# Клавиши в русской раскладке (ЙЦУКЕН → QWERTY)
_RU_KEYS = {"й": "q", "с": "c", "ы": "s", "к": "r", "т": "n"}


def _pad(renderable, top: int = 0, bottom: int = 0) -> Padding:
    """Отступы по краям для панелей, таблиц и текста."""
    return Padding(renderable, (top, MARGIN, bottom, MARGIN))


def info(message: str) -> None:
    console.print(f"{INDENT}[{ACCENT}]ℹ[/] {escape(message)}")


def ok(message: str) -> None:
    console.print(f"{INDENT}[bold green]✓[/] {escape(message)}")


def warn(message: str) -> None:
    console.print(f"{INDENT}[yellow]⚠[/] {escape(message)}")


def error(message: str) -> None:
    console.print(f"{INDENT}[bold red]✗[/] {escape(message)}")


def format_hms(seconds: float) -> str:
    total = int(seconds or 0)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def banner(model: str, lang: str, version: str) -> None:
    left = Text.assemble(("transcriber", f"bold {ACCENT}"), (f" v{version}", "dim"))
    right = Text.assemble(
        ("модель ", "dim"), (model, ACCENT),
        ("  ·  язык ", "dim"), (lang, ACCENT),
        ("  ·  /help", "dim"),
    )
    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="right")
    grid.add_row(left, right)
    console.print(_pad(Panel(grid, box=box.ROUNDED, border_style=ACCENT, padding=(0, 1))))


def video_card(video: VideoInfo) -> None:
    line = Text.assemble(
        ("✓ ", "bold green"),
        (video.platform, f"bold {ACCENT}"),
        (" · ", "dim"),
        (f"«{video.title}»", "bold"),
        (" · ", "dim"),
        (format_hms(video.duration), None),
    )
    if video.uploader:
        line.append(" · ", "dim")
        line.append(video.uploader, "dim")
    console.print(Padding(line, (0, 0, 0, MARGIN)))


# ── ввод в стиле чат-блока (как в opencode) ─────────────────────────


def _box_supported() -> bool:
    try:
        return console.is_terminal and not console.legacy_windows and sys.stdin.isatty()
    except Exception:  # noqa: BLE001
        return False


def _box_width() -> int:
    return max(40, min(console.size.width - MARGIN * 2, 88))


def prompt_box(text: str = "") -> None:
    """Статичный чат-бокс с готовым текстом — тот же вид, что у ask()."""
    width = _box_width()
    inner = width - 2
    top = "╭" + "─" * inner + "╮"
    bottom = "╰" + "─" * inner + "╯"
    pad = " " * max(inner - 3 - len(text), 0)
    console.print(f"{INDENT}[dim]{top}[/]")
    console.print(f"{INDENT}│ [bold {ACCENT}]❯[/] {escape(text)}{pad}[dim]│[/]")
    console.print(f"{INDENT}[dim]{bottom}[/]")


def ask() -> str:
    """Читает строку ввода внутри скруглённого бокса.

    В обычном терминале рисуется рамка, в пайпах и старых консолях —
    простой приглашающий символ.
    """
    if not _box_supported():
        return _plain_ask()

    try:
        width = _box_width()
        inner = width - 2
        top = "╭" + "─" * inner + "╮"
        bottom = "╰" + "─" * inner + "╯"

        console.print(f"{INDENT}[dim]{top}[/]")
        console.print(f"{INDENT}│ [bold {ACCENT}]❯[/] ", end="")
        console.file.flush()
        text = input()

        used = 4 + len(text)  # «│ ❯ » + текст
        remaining = inner - used
        if remaining >= 0:
            target = MARGIN + width - 1
            sys.stdout.write(f"\x1b[1A\x1b[{target}C│\n")
        else:
            sys.stdout.write("\n")
        sys.stdout.flush()
        console.print(f"{INDENT}[dim]{bottom}[/]")
        return text.strip()
    except (EOFError, KeyboardInterrupt):
        # закрываем рамку, чтобы консоль осталась аккуратной
        try:
            bottom = "╰" + "─" * (_box_width() - 2) + "╯"
            console.print(f"{INDENT}[dim]{bottom}[/]")
        except Exception:  # noqa: BLE001
            pass
        raise
    except Exception:  # noqa: BLE001 — рамка не должна ломать ввод
        return _plain_ask()


def _plain_ask() -> str:
    return console.input(f"{INDENT}[bold {ACCENT}]❯[/] ")


def read_menu() -> tuple[str, str]:
    """Читает строку меню: (клавиша, строка целиком).

    Клавиша — первый символ с поправкой на русскую раскладку; строка целиком
    нужна, чтобы в меню можно было сразу вставить ссылку на новое видео.
    """
    try:
        raw = _plain_ask().strip()
    except (EOFError, KeyboardInterrupt):
        return "q", "q"
    if not raw:
        return "", ""
    first = raw[0].lower()
    return _RU_KEYS.get(first, first), raw


def read_key() -> str:
    """Читает одну клавишу (первый символ ввода), понимает русскую раскладку."""
    return read_menu()[0]


# ── прогресс и статусы ──────────────────────────────────────────────


@contextmanager
def status(initial: str) -> Iterator[Callable[[str], None]]:
    """Спиннер с обновляемым текстом — для скачивания модели и загрузки в память."""
    with console.status(f"{INDENT}[{ACCENT}]{escape(initial)}", spinner="dots") as spinner:
        yield lambda message: spinner.update(f"{INDENT}[{ACCENT}]{escape(message)}")


@contextmanager
def download_bar() -> Iterator[Callable[[int, int, float], None]]:
    progress = Progress(
        TextColumn(INDENT),
        SpinnerColumn(style=ACCENT),
        TextColumn("[bold]Скачиваю аудио[/]"),
        BarColumn(bar_width=None),
        TextColumn("{task.percentage:>3.0f}%"),
        DownloadColumn(),
        TransferSpeedColumn(),
        TextColumn(INDENT),
        console=console,
        transient=True,
    )
    with progress:
        task = progress.add_task("audio", total=None)

        def update(done: int, total: int, _speed: float) -> None:
            if total > 0:
                progress.update(task, total=total, completed=min(done, total))
            else:
                progress.update(task)

        yield update


@contextmanager
def recognize_bar(duration: float) -> Iterator[Callable[[float, float], None]]:
    progress = Progress(
        TextColumn(INDENT),
        SpinnerColumn(style=ACCENT),
        TextColumn("[bold]Распознаю речь[/]"),
        BarColumn(bar_width=None),
        TextColumn("{task.fields[timeline]}"),
        TextColumn(INDENT),
        console=console,
        transient=True,
    )
    with progress:
        task = progress.add_task(
            "asr", total=max(duration, 1.0), completed=0, timeline="0:00 / ?"
        )

        def update(position: float, total: float) -> None:
            progress.update(
                task,
                completed=min(position, max(total, 1.0)),
                total=max(total, 1.0),
                timeline=f"{format_hms(position)} / {format_hms(total)}",
            )

        yield update


@contextmanager
def translate_bar(label: str) -> Iterator[Callable[[int, int], None]]:
    progress = Progress(
        TextColumn(INDENT),
        SpinnerColumn(style=ACCENT),
        TextColumn("[bold]{task.description}[/]"),
        BarColumn(bar_width=None),
        TextColumn("{task.fields[parts]}"),
        TextColumn(INDENT),
        console=console,
        transient=True,
    )
    with progress:
        task = progress.add_task(label, total=1, completed=0, parts="")

        def update(done: int, parts_total: int) -> None:
            progress.update(
                task,
                completed=done,
                total=max(parts_total, 1),
                parts=f"{done}/{parts_total} фрагментов",
            )

        yield update


# ── результат, меню, справка ────────────────────────────────────────


def show_result(title: str, text: str, meta: str) -> None:
    console.print()
    header = Text.assemble((title, "bold"), ("\n", None), (meta, "dim"))
    console.print(_pad(Panel(header, box=box.ROUNDED, border_style="dim", padding=(0, 1))))
    console.print(Padding(Text(text), (1, MARGIN, 1, MARGIN)))  # без markup — текст как есть
    console.print()


def menu_line(options: list[tuple[str, str]]) -> None:
    parts = "  ".join(f"[{ACCENT}]\\[{key}][/] {label}" for key, label in options)
    console.print(f"{INDENT}{parts}")


def history_list(entries: list) -> None:
    table = Table(box=box.SIMPLE_HEAD, header_style=ACCENT, show_edge=False)
    table.add_column("#", justify="right")
    table.add_column("когда", style="dim")
    table.add_column("видео")
    table.add_column("язык", style="dim")
    table.add_column("длительность", justify="right", style="dim")
    for index, entry in enumerate(entries, start=1):
        title = entry.title if len(entry.title) <= 48 else entry.title[:47] + "…"
        table.add_row(
            str(index),
            entry.created_str,
            title,
            f"{entry.detected_language}→{entry.output_language}",
            format_hms(entry.duration),
        )
    console.print(_pad(table))


def help_panel() -> None:
    rows = [
        ("/help", "эта справка"),
        ("/model [размер]", "показать или сменить модель Whisper (например, /model small)"),
        ("/lang [ru|en]", "показать или сменить язык результата"),
        ("/history", "последние расшифровки: открыть, скопировать, сохранить"),
        ("/quit", "выход"),
    ]
    table = Table.grid(padding=(0, 2))
    table.add_column(style=ACCENT)
    table.add_column()
    for command, description in rows:
        table.add_row(command, description)
    console.print(_pad(Panel(table, title="команды", border_style="dim", box=box.ROUNDED)))
    console.print(f"{INDENT}[dim]Или просто вставьте ссылку на видео и нажмите Enter.[/]")
