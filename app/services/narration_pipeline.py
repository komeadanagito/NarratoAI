"""AI narration orchestration for one uploaded video."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from pathlib import Path
from typing import Any, Callable

from app.models.batch_schema import NarrationOptions
from app.models.schema import VideoClipParams
from app.config import config
from app.services import task
from app.services.documentary.frame_analysis_service import DocumentaryFrameAnalysisService
from app.services.short_drama_narration_validation import parse_script_timestamp_range
from app.services.tts import SeedAudioProvider
from app.utils import utils


ProgressCallback = Callable[[float, str], None]


class NarrationPipelineError(RuntimeError):
    """An AI narration job failed before a playable intermediate was made."""

    code = "PROCESSING_FAILED"
    status_code = 500

    def __init__(
        self,
        message: str,
        *,
        code: str = "PROCESSING_FAILED",
        status_code: int = 500,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class NarrationPipeline:
    """Analyze, write a script, synthesize speech, and merge one video.

    Provider-specific credentials remain in server configuration.  Injection
    points keep the batch worker deterministic and make provider calls testable
    without network access.
    """

    def __init__(
        self,
        *,
        frame_service: DocumentaryFrameAnalysisService | Any | None = None,
        task_runner: Callable[[str, VideoClipParams], Any] | None = None,
        task_dir_factory: Callable[[str], str] | None = None,
    ) -> None:
        self._frame_service = frame_service or DocumentaryFrameAnalysisService()
        self._task_runner = task_runner or task.start_subclip_unified
        self._task_dir_factory = task_dir_factory or utils.task_dir

    def validate_configuration(self, options: NarrationOptions | None = None) -> None:
        """Fail before enqueueing when an AI provider is not configured."""

        vision_provider = str(config.app.get("vision_llm_provider", "openai")).lower()
        text_provider = str(config.app.get("text_llm_provider", "openai")).lower()
        missing: list[str] = []
        if not config.app.get(f"vision_{vision_provider}_api_key"):
            missing.append(f"vision_{vision_provider}_api_key")
        if not config.app.get(f"vision_{vision_provider}_model_name"):
            missing.append(f"vision_{vision_provider}_model_name")
        if not config.app.get(f"text_{text_provider}_api_key"):
            missing.append(f"text_{text_provider}_api_key")
        if not config.app.get(f"text_{text_provider}_model_name"):
            missing.append(f"text_{text_provider}_model_name")
        seed_provider = SeedAudioProvider.from_config()
        if not seed_provider.app_id or not seed_provider.access_token:
            missing.append("seed_audio.app_id/access_token")
        if not seed_provider.voice_type and not (options and options.voice_id):
            missing.append("seed_audio.voice_type 或 narration.voice_id")
        if missing:
            raise NarrationPipelineError(
                "AI 解说服务未完整配置: " + ", ".join(missing),
                code="PROVIDER_NOT_CONFIGURED",
                status_code=400,
            )

    def process(
        self,
        source_path: str | os.PathLike[str],
        *,
        task_id: str,
        options: NarrationOptions,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        """Return the locally merged narration video for the next stage."""

        try:
            source = Path(source_path).expanduser().resolve(strict=True)
            if not source.is_file():
                raise NarrationPipelineError("AI 解说输入不是有效的视频文件")

            progress = progress_callback or (lambda _value, _message: None)
            progress(1, "正在分析视频画面")

            def analysis_progress(value: float, message: str) -> None:
                # Reserve the final 20% for TTS, clipping, subtitles, and merging.
                progress(max(1.0, min(78.0, float(value) * 0.78)), message)

            script_result = self._frame_service.generate_documentary_script(
                video_path=str(source),
                progress_callback=analysis_progress,
            )
            script = self._await_if_needed(script_result)
            normalized_script = self._normalize_script(script)

            work_dir = Path(self._task_dir_factory(str(task_id))).resolve()
            work_dir.mkdir(parents=True, exist_ok=True)
            script_path = work_dir / "script.json"
            self._write_json_atomic(script_path, normalized_script)

            progress(80, "正在合成解说语音和字幕")
            params = VideoClipParams(
                video_clip_json=normalized_script,
                video_clip_json_path=str(script_path),
                video_origin_path=str(source),
                video_origin_paths=[str(source)],
                video_language=options.language,
                voice_name=options.voice_id or "",
                voice_prompt=options.voice_prompt or "",
                tts_engine="seed_audio",
                bgm_type="",
                bgm_name="",
                subtitle_enabled=True,
            )
            result = self._task_runner(str(task_id), params)
            output_path = self._extract_output_path(result)
            progress(100, "AI 解说视频生成完成")
            return output_path
        except NarrationPipelineError:
            raise
        except Exception as exc:
            code = str(getattr(exc, "code", "PROCESSING_FAILED"))
            status_code = int(getattr(exc, "status_code", 500))
            if code not in {
                "PROVIDER_NOT_CONFIGURED",
                "UPSTREAM_FAILED",
                "PROCESSING_FAILED",
            }:
                code = "PROCESSING_FAILED"
                status_code = 500
            public_message = (
                "AI 解说上游服务调用失败"
                if code == "UPSTREAM_FAILED"
                else "AI 解说处理失败"
            )
            raise NarrationPipelineError(
                public_message,
                code=code,
                status_code=status_code,
            ) from exc

    @staticmethod
    def _await_if_needed(value: Any) -> Any:
        if not inspect.isawaitable(value):
            return value
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(value)
        # The production batch worker has no running event loop. Refuse an
        # accidental synchronous call from one instead of deadlocking it.
        if inspect.iscoroutine(value):
            value.close()
        raise NarrationPipelineError("不能在异步事件循环线程中同步运行 AI 解说")

    @staticmethod
    def _normalize_script(script: Any) -> list[dict[str, Any]]:
        if not isinstance(script, list) or not script:
            raise NarrationPipelineError("视觉模型没有返回可用的解说脚本")

        normalized: list[dict[str, Any]] = []
        previous_end_ms = -1
        seen_timestamps: set[str] = set()
        for index, raw_item in enumerate(script, start=1):
            if not isinstance(raw_item, dict):
                raise NarrationPipelineError("视觉模型返回了无效的解说片段")
            timestamp = str(raw_item.get("timestamp") or "").strip()
            narration = str(raw_item.get("narration") or "").strip()
            if not timestamp or not narration:
                raise NarrationPipelineError("解说片段缺少 timestamp 或 narration")
            try:
                start_ms, end_ms, timestamp = parse_script_timestamp_range(timestamp)
            except ValueError as exc:
                raise NarrationPipelineError(f"解说片段时间戳无效: {exc}") from exc
            if end_ms <= start_ms:
                raise NarrationPipelineError("解说片段结束时间必须晚于开始时间")
            if start_ms < previous_end_ms:
                raise NarrationPipelineError("解说片段必须按时间顺序排列且不能重叠")
            if timestamp in seen_timestamps:
                raise NarrationPipelineError("解说片段包含重复时间戳")
            if len(narration.encode("utf-8")) > 1024:
                raise NarrationPipelineError("单个解说片段超过 Seed Audio 1024 字节限制")
            previous_end_ms = end_ms
            seen_timestamps.add(timestamp)
            normalized.append(
                {
                    **raw_item,
                    # Model-provided IDs are not trusted as file identifiers.
                    "_id": index,
                    "timestamp": timestamp,
                    "picture": str(raw_item.get("picture") or "").strip(),
                    "narration": narration,
                    "OST": 2,
                }
            )
        return normalized

    @staticmethod
    def _write_json_atomic(path: Path, payload: Any) -> None:
        temporary = path.with_suffix(path.suffix + ".part")
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)

    @staticmethod
    def _extract_output_path(result: Any) -> Path:
        videos = result.get("videos") if isinstance(result, dict) else None
        if not isinstance(videos, list) or not videos:
            raise NarrationPipelineError("视频合成流程没有返回输出文件")
        output = Path(str(videos[0])).expanduser().resolve(strict=True)
        if not output.is_file():
            raise NarrationPipelineError("视频合成流程返回的输出文件不存在")
        return output


__all__ = ["NarrationPipeline", "NarrationPipelineError", "ProgressCallback"]
