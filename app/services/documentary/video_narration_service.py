"""Generate a final narration script with one direct video-model request."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from app.config import config
from app.services.llm.manager import LLMServiceManager
from app.services.prompts import PromptManager


ProgressCallback = Callable[[float, str], None]


class VideoNarrationService:
    """Send the complete video to the configured multimodal provider once."""

    def __init__(self, *, provider: Any | None = None) -> None:
        self._provider = provider

    async def generate_narration_script(
        self,
        video_path: str,
        *,
        language: str = "zh-CN",
        video_theme: str = "",
        custom_prompt: str = "",
        progress_callback: ProgressCallback | None = None,
    ) -> list[dict[str, Any]]:
        source = Path(video_path).expanduser().resolve(strict=True)
        if not source.is_file():
            raise ValueError("视频输入不是有效文件")

        progress = progress_callback or (lambda _value, _message: None)
        progress(5, "正在准备视频模型请求")
        prompt = PromptManager.get_prompt(
            category="documentary",
            name="video_narration",
            parameters={
                "language": str(language or "zh-CN").strip(),
                "video_theme": str(video_theme or "未指定").strip(),
                "custom_instructions": str(custom_prompt or "无").strip(),
            },
        )
        prompt_object = PromptManager.get_prompt_object("documentary", "video_narration")
        provider = self._provider or LLMServiceManager.get_vision_provider()

        logger.info(
            "使用视频模型直接生成解说文案: model={}, file={}, size_bytes={}",
            getattr(provider, "model_name", "unknown"),
            source.name,
            source.stat().st_size,
        )
        progress(15, "正在上传并理解完整视频")
        started = time.monotonic()
        raw_response = await provider.analyze_video(
            video=source,
            prompt=prompt,
            system_prompt=prompt_object.get_system_prompt(),
            response_format="json",
            temperature=float(config.app.get("llm_video_temperature", 0.2)),
            max_tokens=int(config.app.get("llm_video_max_tokens", 4096)),
        )
        elapsed = time.monotonic() - started
        items = self.parse_response(raw_response)
        logger.info(
            "视频模型解说文案生成完成: model={}, elapsed_seconds={:.3f}, items={}",
            getattr(provider, "model_name", "unknown"),
            elapsed,
            len(items),
        )
        progress(100, "视频理解和解说文案生成完成")
        return items

    @staticmethod
    def parse_response(raw_response: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_response, str) or not raw_response.strip():
            raise ValueError("视频模型返回了空响应")

        cleaned = raw_response.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"视频模型没有返回合法 JSON（第 {exc.lineno} 行，第 {exc.colno} 列）"
            ) from exc

        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list) or not items:
            raise ValueError("视频模型 JSON 根对象缺少非空 items 数组")
        if not all(isinstance(item, dict) for item in items):
            raise ValueError("视频模型 items 中包含非对象元素")
        return items


__all__ = ["ProgressCallback", "VideoNarrationService"]
