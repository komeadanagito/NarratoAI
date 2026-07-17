#!/usr/bin/env python3
"""Send one real narration request using a saved frame-analysis artifact.

The script deliberately bypasses the application's retry/fallback wrappers so
one invocation always maps to at most one upstream request. It never writes the
API key to disk or stdout.
"""

from __future__ import annotations

import argparse
import json
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
from app.services.generate_narration_script import (  # noqa: E402
    parse_frame_analysis_to_markdown,
)
from app.services.llm.manager import LLMServiceManager  # noqa: E402
from app.services.prompts import PromptManager  # noqa: E402


SYSTEM_PROMPT = "你是一名专业的短视频解说文案撰写专家。"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用真实逐帧分析文本调用当前 NarratoAI 文本模型一次。"
    )
    parser.add_argument(
        "--analysis",
        type=Path,
        help="frame_analysis_*.json 路径；默认使用 storage/temp/analysis 中最新文件。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="调试产物目录；默认写入 storage/temp/narration_debug/<时间戳>。",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--model", help="仅覆盖本次测试使用的模型 ID。")
    parser.add_argument("--base-url", help="仅覆盖本次测试使用的 OpenAI-compatible Base URL。")
    parser.add_argument(
        "--thinking",
        choices=("enabled", "disabled"),
        help="仅为支持该参数的模型显式设置思考模式。",
    )
    credential_group = parser.add_mutually_exclusive_group()
    credential_group.add_argument(
        "--api-key-env",
        help="从指定环境变量读取本次测试 API Key。",
    )
    credential_group.add_argument(
        "--api-key-file",
        type=Path,
        help="从本地文件读取本次测试 API Key；文件内容不会写入调试产物。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只生成并保存真实 prompt，不调用上游模型。",
    )
    return parser.parse_args()


def latest_analysis() -> Path:
    analysis_dir = PROJECT_ROOT / "storage" / "temp" / "analysis"
    candidates = list(analysis_dir.glob("frame_analysis_*.json"))
    if not candidates:
        raise FileNotFoundError(f"没有找到逐帧分析文件: {analysis_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def resolve_path(path: Path | None, *, default: Path | None = None) -> Path:
    selected = path or default
    if selected is None:
        raise ValueError("缺少路径")
    if not selected.is_absolute():
        selected = PROJECT_ROOT / selected
    return selected.resolve()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def analyze_content(content: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "content_chars": len(content),
        "valid_json": False,
        "items_count": 0,
        "items": [],
    }
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        summary["json_error"] = {
            "message": exc.msg,
            "line": exc.lineno,
            "column": exc.colno,
            "position": exc.pos,
        }
        return summary

    summary["valid_json"] = True
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        summary["contract_error"] = "JSON 根节点缺少 items 数组"
        return summary

    summary["items_count"] = len(items)
    summary["items"] = [
        {
            "index": index,
            "keys": sorted(item) if isinstance(item, dict) else [],
            "timestamp": item.get("timestamp") if isinstance(item, dict) else None,
            "picture_chars": len(str(item.get("picture") or ""))
            if isinstance(item, dict)
            else 0,
            "narration_chars": len(str(item.get("narration") or ""))
            if isinstance(item, dict)
            else 0,
        }
        for index, item in enumerate(items)
    ]
    return summary


def main() -> int:
    args = parse_args()
    analysis_path = resolve_path(args.analysis, default=latest_analysis())
    if not analysis_path.is_file():
        raise FileNotFoundError(f"逐帧分析文件不存在: {analysis_path}")

    run_name = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_output = PROJECT_ROOT / "storage" / "temp" / "narration_debug" / run_name
    output_dir = resolve_path(args.output_dir, default=default_output)
    output_dir.mkdir(parents=True, exist_ok=False)

    markdown = parse_frame_analysis_to_markdown(str(analysis_path))
    prompt = PromptManager.get_prompt(
        category="documentary",
        name="narration_generation",
        parameters={"video_frame_description": markdown},
    )

    provider = str(config.app.get("text_llm_provider", "openai")).lower()
    configured_api_key, configured_model, configured_base_url = (
        LLMServiceManager.get_provider_config("text", provider)
    )
    credential_source = "configured text provider"
    api_key = configured_api_key
    if args.api_key_env:
        credential_source = f"environment variable: {args.api_key_env}"
        api_key = os.getenv(args.api_key_env, "").strip()
    elif args.api_key_file:
        key_path = resolve_path(args.api_key_file)
        credential_source = f"local file: {key_path}"
        api_key = key_path.read_text(encoding="utf-8").strip()

    model = str(args.model or configured_model or "").strip()
    base_url = str(args.base_url or configured_base_url or "").strip()
    if not api_key or not model or not base_url:
        raise RuntimeError("文本模型的 API Key、模型名或 Base URL 未完整配置")

    request_record = {
        "analysis_path": str(analysis_path),
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key_configured": bool(api_key),
        "credential_source": credential_source,
        "timeout_seconds": args.timeout,
        "max_retries": 0,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "max_tokens": args.max_tokens,
        "thinking": args.thinking,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "prompt_chars": len(prompt),
    }
    write_json(output_dir / "request.json", request_record)
    (output_dir / "frame_description.md").write_text(markdown, encoding="utf-8")
    (output_dir / "rendered_prompt.txt").write_text(prompt, encoding="utf-8")

    print(f"analysis={analysis_path}")
    print(f"output_dir={output_dir}")
    print(f"model={model}")
    print(f"prompt_chars={len(prompt)}")
    print("api_key_configured=True")

    if args.dry_run:
        print("dry_run=True")
        return 0

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=args.timeout,
        max_retries=0,
    )
    started = time.monotonic()
    try:
        completion_options: dict[str, Any] = {
            "model": model,
            "messages": request_record["messages"],
            "temperature": args.temperature,
            "top_p": args.top_p,
            "max_tokens": args.max_tokens,
            "response_format": {"type": "json_object"},
        }
        if args.thinking:
            completion_options["extra_body"] = {"thinking": {"type": args.thinking}}
        response = client.chat.completions.create(
            **completion_options,
        )
    except Exception as exc:
        elapsed = time.monotonic() - started
        error_record = {
            "elapsed_seconds": round(elapsed, 3),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_json(output_dir / "error.json", error_record)
        print(f"request_succeeded=False elapsed_seconds={elapsed:.3f}")
        print(f"error={type(exc).__name__}: {exc}")
        return 1

    elapsed = time.monotonic() - started
    choice = response.choices[0] if response.choices else None
    content = str(choice.message.content or "") if choice and choice.message else ""
    response_record = response.model_dump(mode="json")
    response_record["debug"] = {
        "elapsed_seconds": round(elapsed, 3),
        "request_id": getattr(response, "_request_id", None),
        "content_analysis": analyze_content(content),
    }
    write_json(output_dir / "response.json", response_record)
    (output_dir / "response_content.txt").write_text(content, encoding="utf-8")

    usage = response.usage
    print(f"request_succeeded=True elapsed_seconds={elapsed:.3f}")
    print(f"finish_reason={choice.finish_reason if choice else None}")
    print(f"prompt_tokens={getattr(usage, 'prompt_tokens', None)}")
    print(f"completion_tokens={getattr(usage, 'completion_tokens', None)}")
    print(f"total_tokens={getattr(usage, 'total_tokens', None)}")
    print("content_analysis=" + json.dumps(analyze_content(content), ensure_ascii=False))
    print("--- raw content ---")
    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
