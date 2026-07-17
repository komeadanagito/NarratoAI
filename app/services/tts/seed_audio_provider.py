from __future__ import annotations

import base64
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from app.config import config


DEFAULT_SEED_AUDIO_URL = "https://openspeech.bytedance.com/api/v3/tts/create"


class SeedAudioError(RuntimeError):
    code = "UPSTREAM_FAILED"
    status_code = 502

    def __init__(self, message: str, *, provider_code: int | None = None):
        super().__init__(message)
        self.provider_code = provider_code


@dataclass(frozen=True)
class SeedAudioResult:
    output_path: str
    duration_ms: int | None = None
    timestamps: list[dict[str, Any]] | None = None
    request_id: str = ""


class SeedAudioProvider:
    """Adapter for Seed Audio ``POST /api/v3/tts/create``."""

    def __init__(
        self,
        *,
        api_key: str,
        api_url: str = DEFAULT_SEED_AUDIO_URL,
        speaker: str = "",
        references: list[dict[str, Any]] | None = None,
        model: str = "seed-audio-1.0",
        audio_config: dict[str, Any] | None = None,
        watermark: dict[str, Any] | None = None,
        timeout: float = 300.0,
        max_retries: int = 3,
        session: Any | None = None,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.api_url = str(api_url or DEFAULT_SEED_AUDIO_URL).strip()
        self.model = str(model or "seed-audio-1.0").strip()
        self.references = [dict(item) for item in (references or []) if isinstance(item, dict)]
        configured_speaker = str(speaker or "").strip()
        if not configured_speaker and self.references:
            configured_speaker = str(self.references[0].get("speaker") or "").strip()
        self.speaker = configured_speaker
        self.audio_config = {
            "format": "mp3",
            "sample_rate": 48000,
            "pitch_rate": 0,
            "speech_rate": 0,
            "loudness_rate": 0,
            **(audio_config or {}),
        }
        self.watermark = dict(watermark or {})
        self.timeout = max(1.0, float(timeout))
        self.max_retries = max(1, int(max_retries))
        self.session = session or requests.Session()

    @classmethod
    def from_config(cls, *, session: Any | None = None) -> "SeedAudioProvider":
        values = getattr(config, "seed_audio", {}) or {}
        api_key_env = str(values.get("api_key_env") or "SEED_AUDIO_API_KEY").strip()
        api_key = (os.getenv(api_key_env) if api_key_env else None) or values.get("api_key", "")
        return cls(
            api_key=api_key or "",
            api_url=os.getenv("SEED_AUDIO_API_URL") or values.get("api_url", DEFAULT_SEED_AUDIO_URL),
            speaker=os.getenv("SEED_AUDIO_SPEAKER") or values.get("speaker", ""),
            references=values.get("references") or [],
            model=os.getenv("SEED_AUDIO_MODEL") or values.get("model", "seed-audio-1.0"),
            audio_config=values.get("audio_config") or {},
            watermark=values.get("watermark") or {},
            timeout=values.get("timeout", 300),
            max_retries=values.get("max_retries", 3),
            session=session,
        )

    @property
    def configured(self) -> bool:
        # Pure-text generation only requires the API key. Speaker/references
        # select a voice or reference mode and are optional.
        return bool(self.api_key)

    def synthesize(
        self,
        text: str,
        output_path: str | os.PathLike[str],
        *,
        voice_id: str = "",
        language: str = "",
        voice_prompt: str = "",
        speed: float = 1.0,
    ) -> SeedAudioResult:
        clean_text = str(text or "").strip()
        if not clean_text:
            raise SeedAudioError("Seed Audio 合成文本不能为空")
        if not self.api_key:
            error = SeedAudioError("Seed Audio 未配置 API Key")
            error.code = "PROVIDER_NOT_CONFIGURED"
            error.status_code = 400
            raise error

        references = self._build_references(voice_id)

        prompt_parts = []
        if str(language or "").strip():
            prompt_parts.append(f"使用 {str(language).strip()} 朗读。")
        if str(voice_prompt or "").strip():
            prompt_parts.append(str(voice_prompt).strip())
        prompt_parts.append(clean_text)
        text_prompt = "\n".join(prompt_parts)
        if len(text_prompt) > 3000:
            raise SeedAudioError("Seed Audio text_prompt 超过 3000 字符限制")

        audio_config = dict(self.audio_config)
        audio_config["speech_rate"] = self._speed_to_rate(speed)
        payload = {
            "model": self.model,
            "text_prompt": text_prompt,
            "audio_config": audio_config,
            "watermark": dict(self.watermark),
        }
        if references:
            payload["references"] = references
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key,
            "X-Api-Request-Id": str(uuid.uuid4()),
        }

        last_error: SeedAudioError | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.session.post(
                    self.api_url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                if response.status_code >= 400:
                    last_error = SeedAudioError(
                        f"Seed Audio 上游请求失败 (HTTP {response.status_code})",
                        provider_code=response.status_code,
                    )
                    if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < self.max_retries:
                        time.sleep(min(2**attempt, 4))
                        continue
                    raise last_error

                audio_bytes, metadata = self._extract_audio(response)
                output = Path(output_path)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(audio_bytes)
                return SeedAudioResult(
                    output_path=str(output),
                    duration_ms=self._duration_ms(metadata),
                    timestamps=self._find_list(metadata, ("timestamps", "timestamp")),
                    request_id=str(
                        self._find_value(metadata, ("request_id", "requestId", "id"))
                        or response.headers.get("x-request-id", "")
                    ),
                )
            except requests.RequestException as exc:
                last_error = SeedAudioError(f"Seed Audio 网络请求失败: {exc.__class__.__name__}")
                if attempt + 1 < self.max_retries:
                    time.sleep(min(2**attempt, 4))
                    continue
                raise last_error from exc

        raise last_error or SeedAudioError("Seed Audio 合成失败")

    def _build_references(self, voice_id: str) -> list[dict[str, Any]]:
        selected = str(voice_id or self.speaker or "").strip()
        if selected:
            return [{"speaker": selected}]
        return [dict(item) for item in self.references]

    @staticmethod
    def _speed_to_rate(speed: float) -> int:
        return max(-50, min(100, round((float(speed) - 1.0) * 100)))

    def _extract_audio(self, response: Any) -> tuple[bytes, dict[str, Any]]:
        content_type = str(response.headers.get("content-type", "")).lower()
        raw = bytes(response.content or b"")
        if content_type.startswith("audio/") or content_type == "application/octet-stream":
            if not raw:
                raise SeedAudioError("Seed Audio 返回了空音频")
            return raw, {}

        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise SeedAudioError("Seed Audio 返回了无效 JSON") from exc
        if not isinstance(payload, dict):
            raise SeedAudioError("Seed Audio 返回格式错误")
        response_code = payload.get("code")
        if response_code not in (None, 0, "0"):
            message = str(payload.get("message") or "未知错误")[:300]
            try:
                provider_code = int(response_code)
            except (TypeError, ValueError):
                provider_code = None
            raise SeedAudioError(
                f"Seed Audio 上游返回错误: {message}",
                provider_code=provider_code,
            )

        encoded = self._find_value(payload, ("audio_data", "audio_base64", "audio"))
        if isinstance(encoded, str):
            if encoded.startswith("data:") and "," in encoded:
                encoded = encoded.split(",", 1)[1]
            try:
                data = base64.b64decode(encoded, validate=True)
                if data:
                    return data, payload
            except (ValueError, TypeError):
                pass

        url = self._find_value(payload, ("audio_url", "download_url", "output_url", "url"))
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            getter = getattr(self.session, "get", requests.get)
            downloaded = getter(url, timeout=self.timeout)
            downloaded.raise_for_status()
            data = bytes(downloaded.content or b"")
            if data:
                return data, payload

        # Some compatible responses use a generic ``data`` field for Base64.
        generic_data = self._find_value(payload, ("data",))
        if isinstance(generic_data, str):
            try:
                data = base64.b64decode(generic_data, validate=True)
                if data:
                    return data, payload
            except (ValueError, TypeError):
                pass
        raise SeedAudioError("Seed Audio 响应中没有可用的音频数据或下载地址")

    @classmethod
    def _find_value(cls, value: Any, keys: tuple[str, ...]) -> Any:
        if isinstance(value, dict):
            for key in keys:
                if key in value and value[key] not in (None, ""):
                    return value[key]
            for child in value.values():
                found = cls._find_value(child, keys)
                if found not in (None, ""):
                    return found
        elif isinstance(value, list):
            for child in value:
                found = cls._find_value(child, keys)
                if found not in (None, ""):
                    return found
        return None

    @classmethod
    def _find_int(cls, payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
        value = cls._find_value(payload, keys)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _duration_ms(cls, payload: dict[str, Any]) -> int | None:
        milliseconds = cls._find_int(payload, ("duration_ms",))
        if milliseconds is not None:
            return milliseconds
        seconds = cls._find_value(payload, ("original_duration", "audio_duration_seconds", "duration"))
        try:
            return round(float(seconds) * 1000) if seconds is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _find_list(cls, payload: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]] | None:
        value = cls._find_value(payload, keys)
        return value if isinstance(value, list) else None


__all__ = ["DEFAULT_SEED_AUDIO_URL", "SeedAudioError", "SeedAudioProvider", "SeedAudioResult"]
