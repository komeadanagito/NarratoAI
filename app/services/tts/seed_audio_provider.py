from __future__ import annotations

import base64
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from app.config import config


DEFAULT_SEED_AUDIO_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
RETRYABLE_CODES = {3003, 3005, 3030, 3031, 3032, 3040}


class SeedAudioError(RuntimeError):
    """Raised when the Seed Audio provider cannot synthesize a request."""

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
    """Volcengine V3 HTTP TTS adapter.

    The adapter intentionally owns all provider-specific payload details so the
    rest of the video pipeline only deals with a local audio file.
    """

    def __init__(
        self,
        *,
        app_id: str,
        access_token: str,
        api_url: str = DEFAULT_SEED_AUDIO_URL,
        voice_type: str = "",
        model: str = "seed-tts-1.1",
        cluster: str = "volcano_tts",
        timeout: float = 60.0,
        max_retries: int = 3,
        session: Any | None = None,
    ) -> None:
        self.app_id = str(app_id or "").strip()
        self.access_token = str(access_token or "").strip()
        self.api_url = str(api_url or DEFAULT_SEED_AUDIO_URL).strip()
        self.voice_type = str(voice_type or "").strip()
        self.model = str(model or "").strip()
        self.cluster = str(cluster or "volcano_tts").strip()
        self.timeout = max(1.0, float(timeout))
        self.max_retries = max(1, int(max_retries))
        self.session = session or requests.Session()

    @classmethod
    def from_config(cls, *, session: Any | None = None) -> "SeedAudioProvider":
        provider_cfg = getattr(config, "seed_audio", {}) or {}
        legacy_cfg = getattr(config, "doubaotts", {}) or {}

        app_id = os.getenv("SEED_AUDIO_APP_ID") or provider_cfg.get("app_id") or provider_cfg.get("appid")
        access_token = (
            os.getenv("SEED_AUDIO_ACCESS_TOKEN")
            or provider_cfg.get("access_token")
            or legacy_cfg.get("token")
        )
        return cls(
            app_id=app_id or legacy_cfg.get("appid", ""),
            access_token=access_token or "",
            api_url=os.getenv("SEED_AUDIO_API_URL")
            or provider_cfg.get("api_url", DEFAULT_SEED_AUDIO_URL),
            voice_type=os.getenv("SEED_AUDIO_VOICE_TYPE")
            or provider_cfg.get("voice_type", ""),
            model=os.getenv("SEED_AUDIO_MODEL")
            or provider_cfg.get("model", "seed-tts-1.1"),
            cluster=provider_cfg.get("cluster", "volcano_tts"),
            timeout=provider_cfg.get("timeout", 60),
            max_retries=provider_cfg.get("max_retries", 3),
            session=session,
        )

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.access_token and self.voice_type)

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
            raise SeedAudioError("Seed Audio 合成文本不能为空", provider_code=3011)
        if len(clean_text.encode("utf-8")) > 1024:
            raise SeedAudioError("Seed Audio 单次合成文本不能超过 1024 UTF-8 字节", provider_code=3010)
        if not self.app_id or not self.access_token:
            error = SeedAudioError("Seed Audio 未配置 app_id 或 access_token")
            error.code = "PROVIDER_NOT_CONFIGURED"
            error.status_code = 400
            raise error

        selected_voice = str(voice_id or self.voice_type).strip()
        if not selected_voice:
            error = SeedAudioError("Seed Audio 未配置 voice_type")
            error.code = "PROVIDER_NOT_CONFIGURED"
            error.status_code = 400
            raise error

        request_id = str(uuid.uuid4())
        audio: dict[str, Any] = {
            "voice_type": selected_voice,
            "encoding": "mp3",
            # The official big-model V3 endpoint defaults to 24 kHz and only
            # documents 8/16 kHz as alternate values; 48 kHz is not accepted.
            "rate": 24000,
            "speed_ratio": max(0.1, min(2.0, float(speed))),
        }
        emotion = self._normalize_emotion(voice_prompt)
        if emotion:
            audio["enable_emotion"] = True
            audio["emotion"] = emotion
        explicit_language = self._normalize_language(language)
        if explicit_language:
            audio["explicit_language"] = explicit_language

        request_payload: dict[str, Any] = {
            "reqid": request_id,
            "text": clean_text,
            "operation": "query",
            "with_timestamp": 1,
        }
        if self.model:
            request_payload["model"] = self.model
        payload = {
            "app": {
                "appid": self.app_id,
                "token": "token",
                "cluster": self.cluster,
            },
            "user": {"uid": "NarratoAI"},
            "audio": audio,
            "request": request_payload,
        }
        headers = {
            "Authorization": f"Bearer;{self.access_token}",
            "Content-Type": "application/json",
        }

        last_error: SeedAudioError | None = None
        for attempt in range(self.max_retries):
            if attempt:
                request_id = str(uuid.uuid4())
                request_payload["reqid"] = request_id
            try:
                response = self.session.post(
                    self.api_url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                result, direct_audio = self._decode_response(response)
                if direct_audio is not None:
                    return self._write_result(output_path, direct_audio, request_id=request_id)

                provider_code = self._to_int(result.get("code"))
                if provider_code is None:
                    raise SeedAudioError("Seed Audio 返回了无效的状态码")
                if response.status_code >= 400 or provider_code not in {0, 3000, 20000000}:
                    last_error = SeedAudioError(
                        f"Seed Audio 上游请求失败 (code={provider_code})",
                        provider_code=provider_code,
                    )
                    retryable = response.status_code in {429, 500, 502, 503, 504} or provider_code in RETRYABLE_CODES
                    if retryable and attempt + 1 < self.max_retries:
                        time.sleep(min(2**attempt, 4))
                        continue
                    raise last_error

                encoded_audio = result.get("data")
                if not isinstance(encoded_audio, str) or not encoded_audio:
                    raise SeedAudioError("Seed Audio 响应缺少音频数据", provider_code=provider_code)
                try:
                    audio_bytes = base64.b64decode(encoded_audio, validate=True)
                except Exception as exc:
                    raise SeedAudioError("Seed Audio 返回了无效的 Base64 音频") from exc

                addition = result.get("addition") or {}
                if isinstance(addition, str):
                    try:
                        addition = json.loads(addition)
                    except json.JSONDecodeError:
                        addition = {}
                if not isinstance(addition, dict):
                    addition = {}
                duration_ms = self._to_int(addition.get("duration"))
                timestamps = addition.get("timestamps") or addition.get("timestamp")
                return self._write_result(
                    output_path,
                    audio_bytes,
                    duration_ms=duration_ms,
                    timestamps=timestamps if isinstance(timestamps, list) else None,
                    request_id=request_id,
                )
            except requests.RequestException as exc:
                last_error = SeedAudioError(f"Seed Audio 网络请求失败: {exc.__class__.__name__}")
                if attempt + 1 < self.max_retries:
                    time.sleep(min(2**attempt, 4))
                    continue
                raise last_error from exc

        raise last_error or SeedAudioError("Seed Audio 合成失败")

    @staticmethod
    def _normalize_language(language: str) -> str:
        normalized = str(language or "").strip().lower()
        aliases = {
            "zh": "zh-cn",
            "zh-cn": "zh-cn",
            "zh-tw": "zh-cn",
            "en": "en",
            "en-us": "en",
            "ja": "ja",
            "ja-jp": "ja",
        }
        return aliases.get(normalized, normalized)

    @staticmethod
    def _normalize_emotion(voice_prompt: str) -> str:
        """Map free-form UI hints to documented V3 emotion values.

        Unsupported prose is deliberately ignored instead of being sent as an
        undocumented ``extra_param`` that would make otherwise valid requests
        fail. Whether an emotion works still depends on the selected voice.
        """

        value = str(voice_prompt or "").strip().lower()
        aliases = (
            (("angry", "生气", "愤怒"), "angry"),
            (("sad", "悲伤", "伤感"), "sad"),
            (("fear", "恐惧", "害怕"), "fear"),
            (("happy", "开心", "高兴", "欢快"), "happy"),
            (("disgust", "厌恶", "嫌弃"), "disgust"),
            (("surprise", "惊讶", "惊喜"), "surprised"),
            (("neutral", "中性", "平静", "克制"), "neutral"),
        )
        for keywords, emotion in aliases:
            if any(keyword in value for keyword in keywords):
                return emotion
        return ""

    @staticmethod
    def _decode_response(response: Any) -> tuple[dict[str, Any], bytes | None]:
        content_type = str(response.headers.get("content-type", "")).lower()
        raw = bytes(response.content or b"")
        if content_type.startswith("audio/") or content_type == "application/octet-stream":
            if response.status_code >= 400:
                return {"code": response.status_code, "message": "audio request failed"}, None
            return {}, raw

        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload, None
            return {
                "code": response.status_code,
                "message": "Seed Audio 返回了无效的 JSON 结构",
            }, None
        except Exception:
            pass

        # Some chunked deployments return one JSON object per line. Keep the
        # last terminal object and concatenate any audio chunks.
        chunks: list[bytes] = []
        terminal: dict[str, Any] = {}
        for line in raw.splitlines():
            try:
                event = json.loads(line)
            except Exception:
                continue
            if not isinstance(event, dict):
                continue
            terminal = event
            data = event.get("data")
            if isinstance(data, str) and data:
                try:
                    chunks.append(base64.b64decode(data))
                except Exception:
                    continue
        if chunks:
            terminal = dict(terminal)
            terminal["code"] = terminal.get("code", 3000)
            terminal["data"] = base64.b64encode(b"".join(chunks)).decode("ascii")
            return terminal, None
        return {
            "code": response.status_code,
            "message": "Seed Audio 返回了无法解析的响应",
        }, None

    @staticmethod
    def _write_result(
        output_path: str | os.PathLike[str],
        audio_bytes: bytes,
        *,
        duration_ms: int | None = None,
        timestamps: list[dict[str, Any]] | None = None,
        request_id: str,
    ) -> SeedAudioResult:
        if not audio_bytes:
            raise SeedAudioError("Seed Audio 返回了空音频")
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.write_bytes(audio_bytes)
        os.replace(temporary, destination)
        return SeedAudioResult(
            output_path=str(destination),
            duration_ms=duration_ms,
            timestamps=timestamps,
            request_id=request_id,
        )

    @staticmethod
    def _to_int(value: Any) -> int | None:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
