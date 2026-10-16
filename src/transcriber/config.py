"""Настройки приложения: ~/.config/transcriber/config.toml."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

APP_DIR = Path.home() / ".config" / "transcriber"
CONFIG_PATH = APP_DIR / "config.toml"
HISTORY_DIR = APP_DIR / "history"

LANGUAGES = ("ru", "en")


@dataclass
class Config:
    """Пользовательские настройки, переживающие перезапуск."""

    model: str = "turbo"      # tiny | base | small | medium | large-v3 | turbo
    lang: str = "ru"          # язык результата: ru | en
    device: str = "auto"      # auto | cpu | cuda
    output_dir: str = ""      # пусто = папка ./output рядом с местом запуска
    max_history: int = 100    # сколько записей истории хранить

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        try:
            with CONFIG_PATH.open("rb") as fh:
                data = tomllib.load(fh)
        except (FileNotFoundError, tomllib.TOMLDecodeError, OSError):
            return cfg
        for key, value in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
        if cfg.lang not in LANGUAGES:
            cfg.lang = "ru"
        return cfg

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        for key, value in asdict(self).items():
            if isinstance(value, bool):
                lines.append(f"{key} = {'true' if value else 'false'}")
            elif isinstance(value, str):
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{key} = "{escaped}"')
            else:
                lines.append(f"{key} = {value}")
        CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def resolve_output_dir(self) -> Path:
        if self.output_dir:
            return Path(self.output_dir).expanduser()
        return Path.cwd() / "output"
