"""Точка входа и главный цикл приложения."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

from . import __version__, history, output, translator, ui
from .config import CONFIG_PATH, Config
from .downloader import DownloadError, download_audio, fetch_info
from .transcriber import (
    MODEL_SIZES,
    TranscriptResult,
    TranscribeError,
    language_name,
    load_model,
    transcribe_audio,
)

_MODEL_ALIASES = {"large-v3-turbo": "turbo", "large": "large-v3"}

_RESULT_MENU = [
    ("c", "копировать"),
    ("s", "сохранить .txt"),
    ("r", "сохранить .srt"),
    ("n", "новое видео"),
    ("q", "выход"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="transcriber",
        description="Консольный транскрибатор видео: вставьте ссылку — получите текст.",
    )
    parser.add_argument("url", nargs="?", help="ссылка на видео (одноразовый режим без меню)")
    parser.add_argument("--lang", choices=["ru", "en"], help="язык результата")
    parser.add_argument("--model", help=f"модель Whisper: {' | '.join(MODEL_SIZES)}")
    parser.add_argument("--out", metavar="ФАЙЛ", help="сохранить результат в .txt или .srt")
    parser.add_argument("--copy", action="store_true", help="скопировать результат в буфер обмена")
    parser.add_argument(
        "--cookies-from-browser",
        metavar="БРАУЗЕР",
        help="взять cookies из браузера: chrome, edge, firefox, brave…",
    )
    parser.add_argument("--keep-audio", action="store_true", help="не удалять скачанное аудио")
    parser.add_argument(
        "--proxy",
        metavar="АДРЕС",
        help="прокси для скачивания и перевода, например socks5://127.0.0.1:1080",
    )
    parser.add_argument(
        "--output-dir", metavar="ПАПКА", help="куда сохранять файлы (по умолчанию ./output)"
    )
    parser.add_argument("--version", action="version", version=f"transcriber {__version__}")
    return parser


def _normalize_model(text: str) -> Optional[str]:
    name = text.strip().lower()
    name = _MODEL_ALIASES.get(name, name)
    return name if name in MODEL_SIZES else None


def _looks_like_url(line: str) -> bool:
    return bool(re.match(r"^https?://", line, re.IGNORECASE)) or (
        " " not in line and "." in line
    )


def _do_copy(text: str) -> None:
    if output.copy_to_clipboard(text):
        ui.ok("Скопировано в буфер обмена.")
    else:
        ui.warn("Не удалось скопировать — буфер обмена недоступен. Сохраните текст в .txt.")


def _ask_default_language() -> str:
    ui.console.print("[bold]Язык результата по умолчанию?[/]")
    ui.console.print(f"  [{ui.ACCENT}][1][/] Русский   [{ui.ACCENT}][2][/] English")
    answer = ui.ask().lower()
    return "en" if answer in ("2", "en", "english", "английский") else "ru"


def _proxy(cfg: Config, args: argparse.Namespace) -> str:
    return (args.proxy or cfg.proxy or "").strip()


def _force_utf8_stdio() -> None:
    """Чтобы русский текст не ломался при перенаправлении вывода в файл или пайп."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


def main(argv: Optional[list[str]] = None) -> int:
    _force_utf8_stdio()
    args = build_parser().parse_args(argv)
    cfg = Config.load()
    first_run = not CONFIG_PATH.exists()

    if args.model:
        model = _normalize_model(args.model)
        if model is None:
            ui.error(f"Неизвестная модель «{args.model}». Доступны: {', '.join(MODEL_SIZES)}")
            return 2
        cfg.model = model
    if args.lang:
        cfg.lang = args.lang
    if args.output_dir:
        cfg.output_dir = args.output_dir

    proxy = _proxy(cfg, args)
    if proxy:
        # requests (переводчик, загрузка моделей) подхватывает прокси из env,
        # yt-dlp получает его явным параметром
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy

    ui.banner(cfg.model, cfg.lang.upper(), __version__)
    if proxy:
        ui.info(f"Скачивание и перевод через прокси: {proxy}")

    if first_run and not args.lang and sys.stdin.isatty():
        cfg.lang = _ask_default_language()
        cfg.save()

    try:
        if args.url:
            return 0 if _process_url(args.url, cfg, args) != "error" else 1
        return _repl(cfg, args)
    except KeyboardInterrupt:
        ui.console.print()
        ui.info("Прервано. До встречи!")
        return 130


def _repl(cfg: Config, args: argparse.Namespace) -> int:
    ui.info("Вставьте ссылку на видео и нажмите Enter. /help — список команд.")
    while True:
        try:
            line = ui.ask()
        except EOFError:
            ui.console.print()
            return 0
        if not line:
            continue
        if line.startswith("/"):
            if _command(line, cfg) == "quit":
                ui.info("До встречи!")
                return 0
            continue
        if not _looks_like_url(line):
            ui.warn("Это не похоже на ссылку. Вставьте URL видео или введите /help.")
            continue
        next_line = line
        while True:
            outcome = _process_url(next_line, cfg, args)
            if not _looks_like_url(outcome):
                break
            next_line = outcome  # ссылка, вставленная прямо в меню результата
        if outcome == "quit":
            ui.info("До встречи!")
            return 0


def _process_url(url: str, cfg: Config, args: argparse.Namespace) -> str:
    proxy = _proxy(cfg, args)

    def on_retry(message: str) -> None:
        ui.info(message)

    ui.info("Получаю информацию о видео…")
    try:
        video = fetch_info(
            url, args.cookies_from_browser, proxy=proxy, on_retry=on_retry
        )
    except DownloadError as exc:
        ui.error(str(exc))
        return "error"
    ui.video_card(video)

    workdir = Path(tempfile.mkdtemp(prefix="transcriber-"))
    audio_path: Optional[Path] = None
    try:
        with ui.download_bar() as update:
            audio_path = download_audio(
                url,
                workdir,
                update,
                args.cookies_from_browser,
                proxy=proxy,
                on_retry=on_retry,
            )

        with ui.status("Подготовка модели…") as set_status:
            model = load_model(cfg.model, cfg.device, on_status=set_status)
        with ui.recognize_bar(video.duration) as update:
            result = transcribe_audio(model, audio_path, on_progress=update)
        # модель остаётся в памяти: следующая ссылка начнёт считаться сразу

        if not result.segments:
            ui.warn("В видео не обнаружена речь.")
            return "done"
    except (DownloadError, TranscribeError) as exc:
        ui.error(str(exc))
        return "error"
    finally:
        if audio_path is not None:
            if args.keep_audio:
                kept = Path.cwd() / audio_path.name
                try:
                    shutil.move(str(audio_path), kept)
                    ui.info(f"Аудио сохранено: {kept}")
                except OSError:
                    pass
        shutil.rmtree(workdir, ignore_errors=True)

    source = result.language
    target = cfg.lang
    translated = source != target
    final_text = result.text

    if translated:
        ui.info(f"Язык видео: {language_name(source)} — перевожу на {language_name(target)}…")
        try:
            with ui.translate_bar("Перевод текста") as update:
                final_text = translator.translate_text(result.text, source, target, update)
        except translator.TranslationError as exc:
            ui.warn(f"{exc}. Показываю текст на языке оригинала.")
            translated = False
            target = source
    else:
        ui.info(f"Язык видео: {language_name(source)} — перевод не нужен.")

    meta = (
        f"{video.platform} · {language_name(source)} · "
        f"{len(result.segments)} реплик · {result.word_count} слов"
    )
    ui.show_result(video.title, final_text, meta)

    try:
        history.save_entry(
            title=video.title,
            url=video.url,
            platform=video.platform,
            model=cfg.model,
            result=result,
            output_text=final_text,
            output_language=target,
            max_entries=cfg.max_history,
        )
    except Exception as exc:  # noqa: BLE001 — история не должна ронять программу
        ui.warn(f"Не удалось сохранить в историю: {exc}")

    return _result_menu(
        title=video.title,
        result=result,
        final_text=final_text,
        target=target,
        translated=translated,
        cfg=cfg,
        args=args,
    )


def _result_menu(
    *,
    title: str,
    result: TranscriptResult,
    final_text: str,
    target: str,
    translated: bool,
    cfg: Config,
    args: argparse.Namespace,
) -> str:
    if args.copy:
        _do_copy(final_text)
    if args.out:
        _save_auto(args.out, title, final_text, result, target, translated)
        return "done"

    ui.menu_line(_RESULT_MENU)
    ui.console.print(f"{ui.INDENT}[dim]Клавиша и Enter — или сразу вставьте новую ссылку.[/]")
    while True:
        key, raw = ui.read_menu()
        if _looks_like_url(raw):
            return raw
        if key == "c":
            _do_copy(final_text)
        elif key == "s":
            path = output.save_txt(final_text, title, cfg.resolve_output_dir())
            ui.ok(f"Сохранено: {path}")
        elif key == "r":
            _save_srt_interactive(title, result, target, translated, cfg)
        elif key == "n":
            return "done"
        elif key == "q":
            return "quit"
        elif key:
            ui.warn("Нет такой команды. Доступно: c, s, r, n, q")


def _save_auto(
    filename: str,
    title: str,
    final_text: str,
    result: TranscriptResult,
    target: str,
    translated: bool,
) -> None:
    path = Path(filename).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".srt":
        texts = None
        if translated:
            with ui.translate_bar("Перевод субтитров") as update:
                texts = translator.translate_segments(result.segments, result.language, target, update)
        path.write_text(output.format_srt(result.segments, texts), encoding="utf-8")
    else:
        path.write_text(final_text.strip() + "\n", encoding="utf-8")
    ui.ok(f"Сохранено: {path}")


def _save_srt_interactive(
    title: str,
    result: TranscriptResult,
    target: str,
    translated: bool,
    cfg: Config,
) -> None:
    texts = None
    if translated:
        ui.console.print(
            f"[dim]SRT: [{ui.ACCENT}]o[/] — язык оригинала, "
            f"[{ui.ACCENT}]t[/] — с переводом[/]"
        )
        key = ui.read_key()
        while key not in ("o", "t", "q"):
            ui.warn("Выберите o или t (или q — отмена)")
            key = ui.read_key()
        if key == "q":
            return
        if key == "t":
            try:
                with ui.translate_bar("Перевод субтитров") as update:
                    texts = translator.translate_segments(
                        result.segments, result.language, target, update
                    )
            except translator.TranslationError as exc:
                ui.error(str(exc))
                return
    path = output.save_srt(result.segments, title, cfg.resolve_output_dir(), texts=texts)
    ui.ok(f"Сохранено: {path}")


def _command(line: str, cfg: Config) -> Optional[str]:
    parts = line[1:].split()
    if not parts:
        return None
    command, rest = parts[0].lower(), parts[1:]

    if command in ("quit", "exit", "q"):
        return "quit"
    if command in ("help", "?", "commands"):
        ui.help_panel()
    elif command == "lang":
        if not rest:
            ui.info(f"Текущий язык результата: {language_name(cfg.lang)}. Смена: /lang ru или /lang en")
        elif rest[0] in ("ru", "en"):
            cfg.lang = rest[0]
            cfg.save()
            ui.ok(f"Язык результата: {language_name(cfg.lang)}")
        else:
            ui.warn("Доступно: /lang ru или /lang en")
    elif command == "model":
        if not rest:
            ui.info(f"Текущая модель: {cfg.model}. Доступны: {', '.join(MODEL_SIZES)}")
        else:
            model = _normalize_model(rest[0])
            if model is None:
                ui.warn(f"Неизвестная модель. Доступны: {', '.join(MODEL_SIZES)}")
            else:
                cfg.model = model
                cfg.save()
                ui.ok(f"Модель: {cfg.model} (скачается при следующем использовании)")
    elif command in ("history", "hist"):
        _show_history(cfg)
    else:
        ui.warn(f"Неизвестная команда «/{command}». Введите /help.")
    return None


def _show_history(cfg: Config) -> None:
    entries = history.load_entries(limit=20)
    if not entries:
        ui.info("История пуста.")
        return
    ui.history_list(entries)
    ui.console.print(
        f"[dim]Введите номер записи (1–{len(entries)}) или Enter — отмена[/]"
    )
    raw = ui.ask().lower()
    if not raw.isdigit():
        return
    index = int(raw)
    if not 1 <= index <= len(entries):
        ui.warn("Нет такой записи.")
        return

    entry = entries[index - 1]
    meta = (
        f"{entry.created_str} · {language_name(entry.detected_language)}→"
        f"{language_name(entry.output_language)} · {entry.model}"
    )
    ui.show_result(entry.title, entry.text, meta)
    ui.menu_line([("c", "копировать"), ("s", ".txt"), ("r", ".srt"), ("любая", "назад")])
    while True:
        key = ui.read_key()
        if key == "c":
            _do_copy(entry.text)
        elif key == "s":
            path = output.save_txt(entry.text, entry.title, cfg.resolve_output_dir())
            ui.ok(f"Сохранено: {path}")
        elif key == "r":
            if entry.translated:
                ui.info("SRT сохранится на языке оригинала.")
            path = output.save_srt(entry.segments, entry.title, cfg.resolve_output_dir())
            ui.ok(f"Сохранено: {path}")
        else:
            return
