#!/usr/bin/env python3
"""Send one real complete-video narration request to the vision model."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openai import OpenAI  # noqa: E402

from app.config import config  # noqa: E402
from app.services.documentary.video_narration_service import VideoNarrationService  # noqa: E402
from app.services.llm.manager import LLMServiceManager  # noqa: E402
from app.services.prompts import PromptManager  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="把一个真实完整视频直接发给当前视觉模型，并保存原始返回。"
    )
    parser.add_argument("--video", type=Path, help="视频路径；默认取 storage/uploads 中最新 source.*。")
    parser.add_argument("--output-dir", type=Path, help="调试产物目录。")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--video-theme", default="未指定")
    parser.add_argument("--custom-prompt", default="无")
    parser.add_argument("--timeout", type=float, default=1200.0)
    parser.add_argument("--video-fps", type=float, default=1.0)
    parser.add_argument("--max-video-bytes", type=int, default=50 * 1024 * 1024)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--model", help="仅覆盖本次测试的视觉模型 ID。")
    parser.add_argument("--base-url", help="仅覆盖本次测试的 OpenAI-compatible Base URL。")
    credential_group = parser.add_mutually_exclusive_group()
    credential_group.add_argument("--api-key-env", help="从指定环境变量读取测试 API Key。")
    credential_group.add_argument("--api-key-file", type=Path, help="从本地文件读取测试 API Key。")
    parser.add_argument("--dry-run", action="store_true", help="只保存 prompt 和请求摘要。")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


def latest_video() -> Path:
    upload_dir = PROJECT_ROOT / "storage" / "uploads"
    candidates = [path for path in upload_dir.glob("*/source.*") if path.is_file()]
    if not candidates:
        raise FileNotFoundError(f"没有找到上传视频: {upload_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime).resolve()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    video_path = resolve_path(args.video) if args.video else latest_video()
    if not video_path.is_file():
        raise FileNotFoundError(f"视频不存在: {video_path}")
    video_size = video_path.stat().st_size
    if video_size > args.max_video_bytes:
        raise ValueError(
            f"视频为 {video_size} 字节，超过直传上限 {args.max_video_bytes} 字节"
        )
    if not 0.2 <= args.video_fps <= 5.0:
        raise ValueError("--video-fps 必须在 0.2 到 5.0 之间")

    run_name = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (
        resolve_path(args.output_dir)
        if args.output_dir
        else PROJECT_ROOT / "storage" / "temp" / "video_narration_debug" / run_name
    )
    output_dir.mkdir(parents=True, exist_ok=False)

    prompt = PromptManager.get_prompt(
        category="documentary",
        name="video_narration",
        parameters={
            "language": args.language,
            "video_theme": args.video_theme,
            "custom_instructions": args.custom_prompt,
        },
    )
    system_prompt = PromptManager.get_prompt_object(
        "documentary", "video_narration"
    ).get_system_prompt()

    provider_name = str(config.app.get("vision_llm_provider", "openai")).lower()
    configured_key, configured_model, configured_base_url = LLMServiceManager.get_provider_config(
        "vision", provider_name
    )
    api_key = str(configured_key or "").strip()
    credential_source = "configured vision provider"
    if args.api_key_env:
        api_key = os.getenv(args.api_key_env, "").strip()
        credential_source = f"environment variable: {args.api_key_env}"
    elif args.api_key_file:
        key_path = resolve_path(args.api_key_file)
        api_key = key_path.read_text(encoding="utf-8").strip()
        credential_source = f"local file: {key_path}"

    model = str(args.model or configured_model or "").strip()
    base_url = str(args.base_url or configured_base_url or "").strip()
    if not api_key or not model or not base_url:
        raise RuntimeError("视觉模型的 API Key、模型名或 Base URL 未完整配置")

    request_summary = {
        "video_path": str(video_path),
        "video_size_bytes": video_size,
        "provider": provider_name,
        "model": model,
        "base_url": base_url,
        "api_key_configured": True,
        "credential_source": credential_source,
        "timeout_seconds": args.timeout,
        "max_retries": 0,
        "video_fps": args.video_fps,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "max_tokens": args.max_tokens,
        "response_format": {"type": "json_object"},
        "content_types": ["video_url", "text"],
        "prompt_chars": len(prompt),
    }
    write_json(output_dir / "request.json", request_summary)
    (output_dir / "rendered_prompt.txt").write_text(prompt, encoding="utf-8")

    print(f"video={video_path}")
    print(f"video_size_bytes={video_size}")
    print(f"output_dir={output_dir}")
    print(f"model={model}")
    if args.dry_run:
        print("dry_run=True")
        return 0

    mime_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"
    video_data = base64.b64encode(video_path.read_bytes()).decode("ascii")
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {
                    "type": "video_url",
                    "video_url": {
                        "url": f"data:{mime_type};base64,{video_data}",
                        "fps": args.video_fps,
                    },
                },
                {"type": "text", "text": prompt},
            ],
        },
    ]
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=args.timeout, max_retries=0)
    started = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=args.temperature,
            top_p=args.top_p,
            max_tokens=args.max_tokens,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        elapsed = time.monotonic() - started
        write_json(
            output_dir / "error.json",
            {
                "elapsed_seconds": round(elapsed, 3),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        print(f"request_succeeded=False elapsed_seconds={elapsed:.3f}")
        print(f"error={type(exc).__name__}: {exc}")
        return 1

    elapsed = time.monotonic() - started
    choice = response.choices[0] if response.choices else None
    content = str(choice.message.content or "") if choice and choice.message else ""
    try:
        items = VideoNarrationService.parse_response(content)
        contract = {"valid": True, "items_count": len(items)}
    except ValueError as exc:
        contract = {"valid": False, "error": str(exc)}
    response_record = response.model_dump(mode="json")
    response_record["debug"] = {
        "elapsed_seconds": round(elapsed, 3),
        "request_id": getattr(response, "_request_id", None),
        "contract": contract,
    }
    write_json(output_dir / "response.json", response_record)
    (output_dir / "response_content.txt").write_text(content, encoding="utf-8")

    print(f"request_succeeded=True elapsed_seconds={elapsed:.3f}")
    print("contract=" + json.dumps(contract, ensure_ascii=False))
    print("--- raw content ---")
    print(content)
    return 0 if contract["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
