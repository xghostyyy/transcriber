"""Тесты настроек: значения по умолчанию, запись и чтение файла."""

import transcriber.config as config_mod
from transcriber.config import Config


def test_defaults_without_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "missing.toml")
    cfg = Config.load()
    assert cfg.model == "turbo"
    assert cfg.lang == "ru"
    assert cfg.device == "auto"


def test_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "APP_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.toml")
    Config(model="small", lang="en", device="cpu", output_dir=str(tmp_path)).save()
    loaded = Config.load()
    assert loaded.model == "small"
    assert loaded.lang == "en"
    assert loaded.device == "cpu"
    assert loaded.output_dir == str(tmp_path)


def test_proxy_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "APP_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.toml")
    Config(proxy="socks5://127.0.0.1:1080").save()
    assert Config.load().proxy == "socks5://127.0.0.1:1080"


def test_unknown_language_falls_back_to_ru(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('lang = "de"\n', encoding="utf-8")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    assert Config.load().lang == "ru"


def test_broken_toml_is_ignored(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text("это точно не toml = = =", encoding="utf-8")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    assert Config.load().model == "turbo"


def test_resolve_output_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "APP_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.toml")
    assert Config(output_dir=str(tmp_path / "куда-то")).resolve_output_dir() == tmp_path / "куда-то"
    assert Config().resolve_output_dir().name == "output"
