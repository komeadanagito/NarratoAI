"""Seed Audio helpers used by the batch AI narration pipeline."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from app.services.tts import SeedAudioError, SeedAudioProvider
from app.utils import utils


@dataclass
class SubtitleMaker:
    """Minimal subtitle timing object retained for the video pipeline."""

    subs: list[str] = field(default_factory=list)
    offset: list[tuple[int, int]] = field(default_factory=list)


def new_sub_maker() -> SubtitleMaker:
    return SubtitleMaker()


def add_subtitle_event(
    sub_maker: SubtitleMaker,
    start_offset: int,
    end_offset: int,
    text: str,
    boundary_type: str = "WordBoundary",
) -> None:
    del boundary_type
    sub_maker.subs.append(text)
    sub_maker.offset.append((start_offset, end_offset))


def get_audio_duration(sub_maker: SubtitleMaker) -> float:
    if not sub_maker.offset:
        return 0.0
    return max(0.0, sub_maker.offset[-1][1] / 10_000_000)


def get_audio_duration_from_file(audio_file: str) -> float:
    """Read the generated audio duration without keeping media handles open."""
    try:
        from moviepy import AudioFileClip

        with AudioFileClip(audio_file) as audio_clip:
            return max(0.0, float(audio_clip.duration or 0.0))
    except Exception as exc:
        logger.warning(f"无法读取音频时长，将使用响应时长或文件估算: {exc}")

    try:
        # Conservative fallback for a typical compressed speech stream.
        return max(1.0, os.path.getsize(audio_file) / 20_000)
    except OSError:
        return 0.0


def seed_audio_tts(
    text: str,
    voice_name: str,
    voice_file: str,
    *,
    speed: float = 1.0,
    language: str = "",
    voice_prompt: str = "",
    provider: SeedAudioProvider | Any | None = None,
) -> SubtitleMaker:
    """Synthesize one narration segment with the configured Seed Audio API."""
    result = (provider or SeedAudioProvider.from_config()).synthesize(
        text,
        voice_file,
        voice_id=voice_name,
        language=language,
        voice_prompt=voice_prompt,
        speed=speed,
    )
    duration_seconds = (
        result.duration_ms / 1000.0
        if result.duration_ms and result.duration_ms > 0
        else get_audio_duration_from_file(voice_file)
    )
    sub_maker = new_sub_maker()
    add_subtitle_event(
        sub_maker,
        0,
        max(1, int(max(duration_seconds, 0.001) * 10_000_000)),
        text,
    )
    return sub_maker


def tts(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_pitch: float,
    voice_file: str,
    tts_engine: str,
    voice_language: str = "",
    voice_prompt: str = "",
    seed_audio_provider: SeedAudioProvider | None = None,
) -> SubtitleMaker:
    """Dispatch TTS for the only engine supported by the batch product."""
    del voice_pitch
    if (tts_engine or "").strip().lower() != "seed_audio":
        raise ValueError(f"批量 AI 解说仅支持 seed_audio，收到: {tts_engine!r}")
    return seed_audio_tts(
        text,
        voice_name,
        voice_file,
        speed=voice_rate,
        language=voice_language,
        voice_prompt=voice_prompt,
        provider=seed_audio_provider,
    )


def _estimate_text_duration(text: str) -> float:
    english_words = len(re.findall(r"\b\w+\b", text))
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    return max(1.0, english_words * 0.35 if english_words > chinese_chars else chinese_chars * 0.3)


def tts_multiple(
    task_id: str,
    list_script: list[dict[str, Any]],
    voice_name: str,
    voice_rate: float,
    voice_pitch: float,
    tts_engine: str = "seed_audio",
    voice_language: str = "",
    voice_prompt: str = "",
) -> list[dict[str, Any]]:
    """Generate narration audio for every non-original-audio script segment."""
    if (tts_engine or "").strip().lower() != "seed_audio":
        raise ValueError(f"批量 AI 解说仅支持 seed_audio，收到: {tts_engine!r}")

    output_dir = utils.task_dir(task_id)
    provider = SeedAudioProvider.from_config()
    results: list[dict[str, Any]] = []

    for item in list_script:
        if item.get("OST") == 1:
            continue

        timestamp = str(item["timestamp"]).replace(":", "_")
        audio_file = os.path.join(output_dir, f"audio_{timestamp}.mp3")
        text = str(item.get("narration") or "").strip()
        if not text:
            raise ValueError(f"时间戳 {item['timestamp']} 的解说文本为空")

        sub_maker = seed_audio_tts(
            text,
            voice_name,
            audio_file,
            speed=voice_rate,
            language=voice_language,
            voice_prompt=voice_prompt,
            provider=provider,
        )
        duration = get_audio_duration_from_file(audio_file) or get_audio_duration(sub_maker)
        if duration <= 0:
            duration = _estimate_text_duration(text)

        results.append(
            {
                "_id": item["_id"],
                "timestamp": item["timestamp"],
                "audio_file": audio_file,
                "subtitle_file": "",
                "duration": duration,
                "text": text,
            }
        )
        logger.info(f"已生成 Seed Audio 配音: {audio_file}")

    return results


__all__ = [
    "SeedAudioError",
    "add_subtitle_event",
    "get_audio_duration",
    "get_audio_duration_from_file",
    "new_sub_maker",
    "seed_audio_tts",
    "tts",
    "tts_multiple",
]
