"""Validated runtime settings for the local batch API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.config import config


def _int_setting(value: object, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _project_path(value: str, project_root: Path) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else project_root / path


@dataclass(frozen=True, slots=True)
class BackendSettings:
    host: str
    port: int
    upload_directory: Path
    allowed_output_roots: tuple[Path, ...]
    allowed_video_extensions: tuple[str, ...]
    max_upload_size_bytes: int
    queue_capacity: int
    ffmpeg_threads: int
    ffmpeg_timeout_seconds: int

    @classmethod
    def load(cls) -> "BackendSettings":
        values = getattr(config, "backend", {}) or {}
        project_root = Path(config.root_dir).resolve()

        configured_roots = values.get("allowed_output_roots") or ["./storage/outputs"]
        env_roots = os.getenv("NARRATO_BACKEND_ALLOWED_OUTPUT_ROOTS", "").strip()
        if env_roots:
            configured_roots = [item for item in env_roots.split(os.pathsep) if item]
        if isinstance(configured_roots, str):
            configured_roots = [configured_roots]
        output_roots = tuple(
            _project_path(str(item), project_root).resolve(strict=False)
            for item in configured_roots
        )
        if not output_roots:
            output_roots = ((project_root / "storage" / "outputs").resolve(strict=False),)

        extensions = values.get("allowed_video_extensions") or [".mp4", ".mov"]
        if isinstance(extensions, str):
            extensions = [extensions]
        normalized_extensions = tuple(
            sorted(
                {
                    value if value.startswith(".") else f".{value}"
                    for item in extensions
                    if (value := str(item).strip().lower())
                }
            )
        ) or (".mov", ".mp4")

        upload_value = os.getenv("NARRATO_BACKEND_UPLOAD_DIRECTORY") or values.get(
            "upload_directory", "./storage/uploads"
        )
        return cls(
            host=str(os.getenv("NARRATO_BACKEND_HOST") or values.get("host", "127.0.0.1")),
            port=_int_setting(
                os.getenv("NARRATO_BACKEND_PORT") or values.get("port"),
                8080,
                minimum=1,
                maximum=65535,
            ),
            upload_directory=_project_path(str(upload_value), project_root).resolve(strict=False),
            allowed_output_roots=output_roots,
            allowed_video_extensions=normalized_extensions,
            max_upload_size_bytes=_int_setting(
                os.getenv("NARRATO_BACKEND_MAX_UPLOAD_SIZE_BYTES")
                or values.get("max_upload_size_bytes"),
                2 * 1024 * 1024 * 1024,
                minimum=1,
                maximum=1024 * 1024 * 1024 * 1024,
            ),
            queue_capacity=_int_setting(
                os.getenv("NARRATO_BACKEND_QUEUE_CAPACITY") or values.get("queue_capacity"),
                32,
                minimum=0,
                maximum=10000,
            ),
            ffmpeg_threads=_int_setting(
                os.getenv("NARRATO_BACKEND_FFMPEG_THREADS") or values.get("ffmpeg_threads"),
                2,
                minimum=1,
                maximum=64,
            ),
            ffmpeg_timeout_seconds=_int_setting(
                os.getenv("NARRATO_BACKEND_FFMPEG_TIMEOUT_SECONDS")
                or values.get("ffmpeg_timeout_seconds"),
                3600,
                minimum=30,
                maximum=24 * 60 * 60,
            ),
        )


__all__ = ["BackendSettings"]
