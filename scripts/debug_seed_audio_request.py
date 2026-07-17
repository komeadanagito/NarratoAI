#!/usr/bin/env python3
"""Send one real Seed Audio TTS request and preserve safe diagnostics."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.tts.seed_audio_provider import (  # noqa: E402
    DEFAULT_SEED_AUDIO_URL,
    SeedAudioProvider,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="向 Seed Audio 发起一次真实 TTS 请求。")
    text_group = parser.add_mutually_exclusive_group()
    text_group.add_argument("--text", default="你好，这是一条语音模型连通性测试。")
    text_group.add_argument("--text-file", type=Path)
    parser.add_argument("--speaker", help="本次请求使用的 speaker；未传时读取模型配置。")
    parser.add_argument("--voice-prompt", default="")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--api-url", help="仅覆盖本次测试的 Seed Audio URL。")
    parser.add_argument("--model", help="仅覆盖本次测试的模型名。")
    parser.add_argument("--timeout", type=float, default=300.0)
    credential_group = parser.add_mutually_exclusive_group()
    credential_group.add_argument("--api-key-env", help="从指定环境变量读取测试 API Key。")
    credential_group.add_argument("--api-key-file", type=Path, help="从本地文件读取测试 API Key。")
    credential_group.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="从隐藏终端输入读取测试 API Key，不写入磁盘。",
    )
    parser.add_argument("--dry-run", action="store_true", help="只保存脱敏请求，不调用上游。")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def sanitized_response_body(response: requests.Response) -> Any:
    content_type = str(response.headers.get("content-type", "")).lower()
    if content_type.startswith("audio/") or content_type == "application/octet-stream":
        return {"audio_body_bytes": len(response.content)}
    try:
        payload = response.json()
    except ValueError:
        return {"text_preview": response.text[:2000], "body_bytes": len(response.content)}

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            result = {}
            for key, child in value.items():
                if key.lower() in {"audio", "audio_data", "audio_base64", "data"} and isinstance(
                    child, str
                ):
                    result[key] = f"<omitted {len(child)} chars>"
                else:
                    result[key] = scrub(child)
            return result
        if isinstance(value, list):
            return [scrub(child) for child in value]
        return value

    return scrub(payload)


def main() -> int:
    args = parse_args()
    configured = SeedAudioProvider.from_config()
    api_key = configured.api_key
    credential_source = "configured Seed Audio provider"
    if args.api_key_env:
        api_key = os.getenv(args.api_key_env, "").strip()
        credential_source = f"environment variable: {args.api_key_env}"
    elif args.api_key_file:
        key_path = resolve_path(args.api_key_file)
        api_key = key_path.read_text(encoding="utf-8").strip()
        credential_source = f"local file: {key_path}"
    elif args.api_key_stdin:
        api_key = getpass.getpass("Seed Audio API Key: ").strip()
        credential_source = "hidden terminal input"

    speaker = str(args.speaker or configured.speaker or "").strip()
    api_url = str(args.api_url or configured.api_url or DEFAULT_SEED_AUDIO_URL).strip()
    model = str(args.model or configured.model or "seed-audio-1.0").strip()
    if not api_key:
        raise RuntimeError("Seed Audio API Key 未配置；使用 --api-key-env 或 --api-key-file 提供")

    if args.text_file:
        text = resolve_path(args.text_file).read_text(encoding="utf-8").strip()
    else:
        text = str(args.text or "").strip()
    if not text:
        raise ValueError("测试文本不能为空")
    output_dir = (
        resolve_path(args.output_dir)
        if args.output_dir
        else PROJECT_ROOT
        / "storage"
        / "temp"
        / "seed_audio_debug"
        / datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    output_dir.mkdir(parents=True, exist_ok=False)

    prompt_parts = []
    if args.language:
        prompt_parts.append(f"使用 {args.language} 朗读。")
    if args.voice_prompt:
        prompt_parts.append(args.voice_prompt.strip())
    prompt_parts.append(text)
    text_prompt = "\n".join(prompt_parts)
    if len(text_prompt) > 3000:
        raise ValueError("Seed Audio text_prompt 超过 3000 字符限制")
    payload = {
        "model": model,
        "text_prompt": text_prompt,
        "audio_config": dict(configured.audio_config),
        "watermark": dict(configured.watermark),
    }
    if speaker:
        payload["references"] = [{"speaker": speaker}]
    request_id = str(uuid.uuid4())
    write_json(
        output_dir / "request.json",
        {
            "api_url": api_url,
            "api_key_configured": True,
            "credential_source": credential_source,
            "timeout_seconds": args.timeout,
            "max_retries": 0,
            "request_id": request_id,
            "payload": payload,
        },
    )
    print(f"output_dir={output_dir}")
    print(f"model={model}")
    print(f"generation_mode={'speaker_reference' if speaker else 'pure_text'}")
    print(f"speaker={speaker or '<not used>'}")
    print(f"text_prompt_chars={len(text_prompt)}")
    if args.dry_run:
        print("dry_run=True")
        return 0

    started = time.monotonic()
    try:
        response = requests.post(
            api_url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": api_key,
                "X-Api-Request-Id": request_id,
            },
            timeout=args.timeout,
        )
    except requests.RequestException as exc:
        elapsed = time.monotonic() - started
        write_json(
            output_dir / "error.json",
            {
                "elapsed_seconds": round(elapsed, 3),
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        print(f"request_succeeded=False elapsed_seconds={elapsed:.3f}")
        print(f"error={type(exc).__name__}: {exc}")
        return 1

    elapsed = time.monotonic() - started
    response_record = {
        "elapsed_seconds": round(elapsed, 3),
        "status_code": response.status_code,
        "headers": {
            key: value
            for key, value in response.headers.items()
            if key.lower() in {"content-type", "x-request-id", "x-tt-logid"}
        },
        "body": sanitized_response_body(response),
    }
    write_json(output_dir / "response.json", response_record)
    if response.status_code >= 400:
        print(f"request_succeeded=False elapsed_seconds={elapsed:.3f}")
        print(f"http_status={response.status_code}")
        print("response=" + json.dumps(response_record["body"], ensure_ascii=False))
        return 1

    try:
        audio_bytes, metadata = configured._extract_audio(response)
    except Exception as exc:
        print(f"request_succeeded=False elapsed_seconds={elapsed:.3f}")
        print(f"error={type(exc).__name__}: {exc}")
        return 2

    output_path = output_dir / f"output.{configured.audio_config.get('format', 'mp3')}"
    output_path.write_bytes(audio_bytes)
    write_json(output_dir / "metadata.json", sanitized_response_body(response) if metadata else {})
    print(f"request_succeeded=True elapsed_seconds={elapsed:.3f}")
    print(f"audio_path={output_path}")
    print(f"audio_bytes={len(audio_bytes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
