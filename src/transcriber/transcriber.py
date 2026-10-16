"""Распознавание речи через faster-whisper (локально, без API-ключей)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# tqdm-бары и служебные предупреждения huggingface отключены — показываем свой индикатор
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import logging  # noqa: E402

logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

from faster_whisper import WhisperModel  # noqa: E402
from faster_whisper.utils import download_model  # noqa: E402

MODEL_SIZES = ("tiny", "base", "small", "medium", "large-v3", "turbo")

MODEL_APPROX_SIZE = {
    "tiny": "75 МБ",
    "base": "145 МБ",
    "small": "0.5 ГБ",
    "medium": "1.5 ГБ",
    "large-v3": "3.1 ГБ",
    "turbo": "1.6 ГБ",
}

LANGUAGE_NAMES = {
    "ru": "русский", "en": "английский", "uk": "украинский", "be": "белорусский",
    "kk": "казахский", "uz": "узбекский", "az": "азербайджанский", "hy": "армянский",
    "ka": "грузинский", "ky": "кыргызский", "tg": "таджикский", "de": "немецкий",
    "fr": "французский", "es": "испанский", "it": "итальянский", "pt": "португальский",
    "pl": "польский", "cs": "чешский", "tr": "турецкий", "ar": "арабский",
    "fa": "персидский", "he": "иврит", "hi": "хинди", "zh": "китайский",
    "ja": "японский", "ko": "корейский", "nl": "нидерландский", "sv": "шведский",
    "no": "норвежский", "da": "датский", "fi": "финский", "el": "греческий",
    "id": "индонезийский", "ro": "румынский", "hu": "венгерский", "bg": "болгарский",
    "sr": "сербский", "hr": "хорватский", "sk": "словацкий", "sl": "словенский",
    "lt": "литовский", "lv": "латышский", "et": "эстонский", "vi": "вьетнамский",
    "th": "тайский",
}


class TranscribeError(Exception):
    """Понятная человеку ошибка распознавания."""


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code or "неизвестен")


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class TranscriptResult:
    segments: list[Segment]
    language: str
    language_probability: float
    duration: float

    @property
    def text(self) -> str:
        return "\n".join(s.text for s in self.segments if s.text)

    @property
    def word_count(self) -> int:
        return sum(len(s.text.split()) for s in self.segments)


def _ensure_model(model_name: str, on_status: Callable[[str], None]) -> str:
    """Возвращает локальный путь к модели, скачивая её при первом запуске."""
    try:
        return str(download_model(model_name, local_files_only=True))
    except Exception:  # noqa: BLE001 — модели просто нет в кэше
        pass
    on_status(
        f"Скачиваю модель «{model_name}» (~{MODEL_APPROX_SIZE.get(model_name, '?')}) "
        "— это займёт время только в первый раз"
    )
    try:
        return str(download_model(model_name))
    except Exception as exc:  # noqa: BLE001
        raise TranscribeError(
            f"Не удалось скачать модель «{model_name}»: {exc}"
        ) from exc


def _resolve_device(preference: str) -> tuple[str, str]:
    if preference == "cuda":
        return "cuda", "float16"
    if preference == "cpu":
        return "cpu", "int8"
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:  # noqa: BLE001
        pass
    return "cpu", "int8"


def _probe(model: WhisperModel) -> None:
    """Прогоняет секунду тишины, чтобы поймать отсутствие CUDA-библиотек заранее."""
    import numpy as np

    silence = np.zeros(16000, dtype=np.float32)
    segments, _ = model.transcribe(silence, beam_size=1, vad_filter=False)
    for _segment in segments:
        pass


def load_model(
    model_name: str,
    device_preference: str = "auto",
    on_status: Optional[Callable[[str], None]] = None,
) -> WhisperModel:
    """Готовит модель к работе: при необходимости скачивает и держит в памяти."""
    status = on_status or (lambda _msg: None)
    model_path = _ensure_model(model_name, status)
    status("Загружаю модель в память…")
    device, compute_type = _resolve_device(device_preference)

    def make(dev: str, ctype: str) -> WhisperModel:
        return WhisperModel(
            model_path,
            device=dev,
            compute_type=ctype,
            cpu_threads=os.cpu_count() or 4,
        )

    if device == "cuda":
        try:
            model = make("cuda", "float16")
            _probe(model)
            return model
        except Exception:  # noqa: BLE001 — драйвер есть, а библиотек может не быть
            status("GPU недоступен (нет CUDA-библиотек), использую CPU…")

    try:
        return make("cpu", "int8")
    except Exception as exc:  # noqa: BLE001
        raise TranscribeError(f"Не удалось загрузить модель: {exc}") from exc


def transcribe_audio(
    model: WhisperModel,
    audio_path: Path,
    on_progress: Optional[Callable[[float, float], None]] = None,
) -> TranscriptResult:
    """Распознаёт речь. Язык определяется автоматически."""
    progress = on_progress or (lambda _pos, _total: None)
    try:
        segments_iter, info = model.transcribe(
            str(audio_path),
            beam_size=5,
            vad_filter=True,
            language=None,  # автоопределение
        )
        duration = float(info.duration or 0)
        total = duration
        segments: list[Segment] = []
        for seg in segments_iter:
            text = (seg.text or "").strip()
            if text:
                segments.append(Segment(start=float(seg.start), end=float(seg.end), text=text))
            total = total or float(seg.end) or 1.0
            progress(float(seg.end), total)
    except Exception as exc:  # noqa: BLE001
        raise TranscribeError(f"Ошибка распознавания: {exc}") from exc

    return TranscriptResult(
        segments=segments,
        language=str(info.language),
        language_probability=float(info.language_probability or 0),
        duration=duration or (segments[-1].end if segments else 0.0),
    )
