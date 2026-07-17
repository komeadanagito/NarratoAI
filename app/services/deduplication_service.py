"""FFmpeg based, single-video content transformation service.

The service deliberately accepts a structural ``DeduplicationOptions`` object
instead of importing the HTTP layer's Pydantic model.  This keeps media
processing independent from FastAPI while still accepting that model (or a
plain mapping) at runtime.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


ProgressCallback = Callable[[int, str], None]
CommandRunner = Callable[..., Any]


class DeduplicationOptions(Protocol):
    change_file_hash: bool
    reencode: bool
    color_noise_tweak: bool
    border_mode: str
    sticker: bool
    subtitle_mask: bool
    crop_scale: bool
    mirror: bool
    speed_tweak: bool


class DeduplicationError(RuntimeError):
    """A media-processing error suitable for storing in ``VideoJob.error``."""

    def __init__(self, message: str, *, code: str = "PROCESSING_FAILED") -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_error(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    width: int
    height: int
    has_audio: bool


@dataclass(frozen=True)
class _Options:
    change_file_hash: bool = True
    reencode: bool = True
    color_noise_tweak: bool = False
    border_mode: str = "none"
    sticker: bool = False
    subtitle_mask: bool = False
    crop_scale: bool = False
    mirror: bool = False
    speed_tweak: bool = False


class DeduplicationService:
    """Build and execute a safe FFmpeg transformation command.

    ``runner`` and ``random_source`` are injectable so command construction and
    random decisions can be tested without launching FFmpeg.
    """

    _OUTPUT_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv"})

    def __init__(
        self,
        *,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        sticker_directory: str | os.PathLike[str] | None = None,
        border_directory: str | os.PathLike[str] | None = None,
        ffmpeg_threads: int = 2,
        process_timeout: int = 3600,
        probe_timeout: int = 30,
        runner: CommandRunner = subprocess.run,
        random_source: Any | None = None,
    ) -> None:
        self.ffmpeg_binary = str(ffmpeg_binary)
        self.ffprobe_binary = str(ffprobe_binary)
        self.runner = runner
        self.ffmpeg_threads = max(1, min(64, int(ffmpeg_threads)))
        self.process_timeout = max(30, int(process_timeout))
        self.probe_timeout = max(1, int(probe_timeout))
        self.random = random_source or secrets.SystemRandom()
        default_stickers = Path(__file__).resolve().parents[2] / "resource" / "stickers"
        default_borders = Path(__file__).resolve().parents[2] / "resource" / "borders"
        self._sticker_directory_configured = sticker_directory is not None
        self.sticker_directory = Path(sticker_directory or default_stickers)
        self.border_directory = Path(border_directory or default_borders)

    def apply(
        self,
        input_path: str,
        output_path: str,
        options: DeduplicationOptions | Mapping[str, Any],
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> str:
        normalized = self._normalize_options(options)
        source, destination = self._validate_paths(input_path, output_path)
        self._emit(progress_callback, 0, "正在检查输入视频")
        media = self._probe(source, invalid_input=True)

        metadata_id = self._random_hex(16)
        temporary = self._temporary_output(destination, metadata_id)
        try:
            command = self._build_command(
                source,
                temporary,
                media,
                normalized,
                metadata_id=metadata_id,
            )
            self._emit(progress_callback, 10, "正在处理视频")
            result = self._run(command)
            if result.returncode != 0:
                detail = self._safe_stderr(result.stderr)
                message = "FFmpeg 视频处理失败"
                if detail:
                    message = f"{message}: {detail}"
                raise DeduplicationError(message)

            if not temporary.is_file() or temporary.stat().st_size <= 0:
                raise DeduplicationError("FFmpeg 未生成有效的输出文件")

            self._emit(progress_callback, 90, "正在验证输出视频")
            output_media = self._probe(temporary, invalid_input=False)
            if output_media.duration <= 0 or output_media.width <= 0 or output_media.height <= 0:
                raise DeduplicationError("输出视频媒体信息无效")

            # The caller creates unique names.  Refuse to overwrite if a race
            # nevertheless creates the final path while FFmpeg is running.
            if destination.exists():
                raise DeduplicationError("输出文件已存在", code="INVALID_REQUEST")
            os.replace(temporary, destination)
            self._emit(progress_callback, 100, "处理完成")
            return str(destination)
        except DeduplicationError:
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            raise DeduplicationError(f"媒体处理执行失败: {exc}") from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _validate_paths(self, input_path: str, output_path: str) -> tuple[Path, Path]:
        if not input_path or not output_path:
            raise DeduplicationError("输入和输出路径不能为空", code="INVALID_REQUEST")

        try:
            source = Path(input_path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise DeduplicationError("输入视频不存在", code="UNSUPPORTED_MEDIA") from exc
        if not source.is_file():
            raise DeduplicationError("输入路径不是普通文件", code="UNSUPPORTED_MEDIA")

        try:
            destination = Path(output_path).expanduser().resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise DeduplicationError("输出路径无效", code="INVALID_REQUEST") from exc
        if source == destination:
            raise DeduplicationError("输入和输出路径不能相同", code="INVALID_REQUEST")
        if destination.suffix.lower() not in self._OUTPUT_EXTENSIONS:
            raise DeduplicationError("输出格式必须是 MP4、MOV 或 MKV", code="INVALID_REQUEST")
        if not destination.parent.is_dir():
            raise DeduplicationError("输出目录不存在", code="INVALID_REQUEST")
        if destination.exists():
            raise DeduplicationError("输出文件已存在", code="INVALID_REQUEST")
        return source, destination

    def _probe(self, path: Path, *, invalid_input: bool) -> MediaInfo:
        command = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ]
        try:
            result = self._run(command)
        except (OSError, subprocess.SubprocessError) as exc:
            code = "UNSUPPORTED_MEDIA" if invalid_input else "PROCESSING_FAILED"
            raise DeduplicationError(f"ffprobe 执行失败: {exc}", code=code) from exc
        if result.returncode != 0:
            code = "UNSUPPORTED_MEDIA" if invalid_input else "PROCESSING_FAILED"
            detail = self._safe_stderr(result.stderr)
            message = "输入文件不是受支持的视频" if invalid_input else "输出视频校验失败"
            if detail:
                message = f"{message}: {detail}"
            raise DeduplicationError(message, code=code)

        try:
            payload = json.loads(result.stdout or "{}")
            streams = payload.get("streams") or []
            video = next(stream for stream in streams if stream.get("codec_type") == "video")
            width = int(video["width"])
            height = int(video["height"])
            duration_raw = video.get("duration") or (payload.get("format") or {}).get("duration")
            duration = float(duration_raw)
            has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
            if width <= 0 or height <= 0 or duration <= 0:
                raise ValueError("invalid dimensions or duration")
        except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as exc:
            code = "UNSUPPORTED_MEDIA" if invalid_input else "PROCESSING_FAILED"
            message = "输入文件缺少有效视频流" if invalid_input else "输出文件缺少有效视频流"
            raise DeduplicationError(message, code=code) from exc
        return MediaInfo(duration=duration, width=width, height=height, has_audio=has_audio)

    def _build_command(
        self,
        source: Path,
        destination: Path,
        media: MediaInfo,
        options: _Options,
        *,
        metadata_id: str,
    ) -> list[str]:
        border_path = self._select_border() if options.border_mode == "asset" else None
        sticker_path = self._select_sticker() if options.sticker else None
        next_input_index = 1
        border_input_index = None
        sticker_input_index = None
        if border_path is not None:
            border_input_index = next_input_index
            next_input_index += 1
        if sticker_path is not None:
            sticker_input_index = next_input_index
        graph, video_label, audio_label, has_video_filter, speed = self._build_filter_graph(
            media,
            options,
            sticker_requested=options.sticker,
            border_input_index=border_input_index,
            sticker_input_index=sticker_input_index,
        )

        command = [
            self.ffmpeg_binary,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(source),
        ]
        if border_path is not None:
            command.extend(["-i", str(border_path)])
        if sticker_path is not None:
            # A still image is enough: overlay repeats the last secondary
            # frame.  ``-loop 1`` would make that input infinite and can keep
            # FFmpeg alive after the main video has ended.
            command.extend(["-i", str(sticker_path)])

        if has_video_filter:
            command.extend(["-filter_complex", ";".join(graph), "-map", f"[{video_label}]"])
        else:
            command.extend(["-map", "0:v:0"])

        if media.has_audio:
            if audio_label:
                command.extend(["-map", f"[{audio_label}]"])
            else:
                command.extend(["-map", "0:a:0"])
        else:
            command.append("-an")

        must_encode_video = options.reencode or has_video_filter
        if must_encode_video:
            command.extend(
                [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    "-threads",
                    str(self.ffmpeg_threads),
                ]
            )
            if media.has_audio:
                if speed is not None:
                    command.extend(["-c:a", "aac", "-b:a", "192k"])
                else:
                    command.extend(["-c:a", "copy"])
        else:
            # No visual/audio filter and re-encoding was not requested: remux.
            command.extend(["-c", "copy"])

        command.extend(["-map_metadata", "0"])
        if options.change_file_hash:
            command.extend(["-metadata", f"comment=NarratoAI dedup {metadata_id}"])
        if destination.suffix.lower() in {".mp4", ".mov"}:
            command.extend(["-movflags", "+faststart"])
        command.extend(["-avoid_negative_ts", "make_zero", str(destination)])
        return command

    def _build_filter_graph(
        self,
        media: MediaInfo,
        options: _Options,
        *,
        sticker_requested: bool,
        border_input_index: int | None,
        sticker_input_index: int | None,
    ) -> tuple[list[str], str, str | None, bool, float | None]:
        graph: list[str] = []
        current = "0:v:0"
        counter = 0

        def label(prefix: str) -> str:
            nonlocal counter
            counter += 1
            return f"{prefix}{counter}"

        def chain(filters: Sequence[str], prefix: str = "v") -> None:
            nonlocal current
            if not filters:
                return
            output = label(prefix)
            graph.append(f"[{current}]{','.join(filters)}[{output}]")
            current = output

        initial_filters: list[str] = []
        if options.color_noise_tweak:
            brightness = self.random.uniform(-0.025, 0.025)
            contrast = self.random.uniform(0.98, 1.02)
            saturation = self.random.uniform(0.98, 1.02)
            noise = self.random.uniform(1.0, 2.0)
            initial_filters.extend(
                [
                    "eq="
                    f"brightness={brightness:.4f}:contrast={contrast:.4f}:saturation={saturation:.4f}",
                    f"noise=alls={noise:.3f}:allf=t+u",
                ]
            )
        if options.crop_scale:
            ratio = self.random.uniform(0.985, 0.995)
            crop_width = self._even(max(2, int(media.width * ratio)))
            crop_height = self._even(max(2, int(media.height * ratio)))
            max_x = max(0, media.width - crop_width)
            max_y = max(0, media.height - crop_height)
            crop_x = self._even(int(self.random.uniform(0, max_x))) if max_x else 0
            crop_y = self._even(int(self.random.uniform(0, max_y))) if max_y else 0
            initial_filters.extend(
                [
                    f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y}",
                    f"scale={self._even(media.width)}:{self._even(media.height)}",
                ]
            )
        if options.mirror and self.random.random() < 0.5:
            initial_filters.append("hflip")
        chain(initial_filters)

        if options.border_mode == "solid":
            ratio = self.random.uniform(0.96, 0.98)
            inner_width = self._even(max(2, int(media.width * ratio)))
            inner_height = self._even(max(2, int(media.height * ratio)))
            chain(
                [
                    f"scale={inner_width}:{inner_height}:force_original_aspect_ratio=decrease",
                    f"pad={self._even(media.width)}:{self._even(media.height)}:(ow-iw)/2:(oh-ih)/2:color=black",
                ],
                "solid",
            )
        elif options.border_mode == "blurred":
            target_width = self._even(media.width)
            target_height = self._even(media.height)
            ratio = self.random.uniform(0.91, 0.95)
            foreground_width = self._even(max(2, int(target_width * ratio)))
            foreground_height = self._even(max(2, int(target_height * ratio)))
            background = label("bg")
            foreground = label("fg")
            blurred = label("blur")
            scaled = label("front")
            output = label("border")
            graph.append(f"[{current}]split=2[{background}][{foreground}]")
            graph.append(
                f"[{background}]scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
                f"crop={target_width}:{target_height},boxblur=luma_radius=20:luma_power=2[{blurred}]"
            )
            graph.append(
                f"[{foreground}]scale={foreground_width}:{foreground_height}:"
                f"force_original_aspect_ratio=decrease[{scaled}]"
            )
            graph.append(f"[{blurred}][{scaled}]overlay=(W-w)/2:(H-h)/2[{output}]")
            current = output
        elif options.border_mode == "asset" and border_input_index is not None:
            target_width = self._even(media.width)
            target_height = self._even(media.height)
            frame = label("frame")
            output = label("assetborder")
            graph.append(
                f"[{border_input_index}:v:0]format=rgba,"
                f"scale={target_width}:{target_height}:flags=lanczos[{frame}]"
            )
            graph.append(
                f"[{current}][{frame}]overlay=0:0:eof_action=repeat:shortest=0[{output}]"
            )
            current = output

        if options.subtitle_mask:
            x, y, width, height = self._subtitle_region(media)
            base = label("maskbase")
            source = label("masksrc")
            softened = label("softmask")
            output = label("masked")
            radius = max(2, min(20, height // 8))
            graph.append(f"[{current}]split=2[{base}][{source}]")
            graph.append(
                f"[{source}]crop={width}:{height}:{x}:{y},"
                f"boxblur=luma_radius={radius}:luma_power=2[{softened}]"
            )
            graph.append(f"[{base}][{softened}]overlay={x}:{y}[{output}]")
            current = output

        if sticker_input_index is not None:
            sticker = label("sticker")
            output = label("stuck")
            sticker_width = self._even(max(24, int(media.width * self.random.uniform(0.06, 0.10))))
            opacity = self.random.uniform(0.35, 0.55)
            margin = max(8, int(min(media.width, media.height) * 0.02))
            positions = [
                (str(margin), str(margin)),
                (f"W-w-{margin}", str(margin)),
                (str(margin), f"H-h-{margin}"),
                (f"W-w-{margin}", f"H-h-{margin}"),
            ]
            x, y = self.random.choice(positions)
            graph.append(
                f"[{sticker_input_index}:v:0]format=rgba,scale={sticker_width}:-2,"
                f"colorchannelmixer=aa={opacity:.3f}[{sticker}]"
            )
            graph.append(
                f"[{current}][{sticker}]overlay={x}:{y}:eof_action=repeat:shortest=0[{output}]"
            )
            current = output
        elif sticker_requested:
            # The repository may be deployed without optional PNG assets. A
            # small code-native translucent badge keeps the API switch usable
            # while preserving the stricter PNG allow-list when assets exist.
            badge_width = self._even(max(24, int(media.width * self.random.uniform(0.05, 0.08))))
            badge_height = self._even(max(16, int(badge_width * 0.65)))
            margin = max(8, int(min(media.width, media.height) * 0.02))
            positions = [
                (margin, margin),
                (max(margin, media.width - badge_width - margin), margin),
                (margin, max(margin, media.height - badge_height - margin)),
                (
                    max(margin, media.width - badge_width - margin),
                    max(margin, media.height - badge_height - margin),
                ),
            ]
            x, y = self.random.choice(positions)
            opacity = self.random.uniform(0.12, 0.22)
            chain(
                [
                    f"drawbox=x={x}:y={y}:w={badge_width}:h={badge_height}:"
                    f"color=white@{opacity:.3f}:t=fill",
                    f"drawbox=x={x}:y={y}:w={badge_width}:h={badge_height}:"
                    "color=white@0.28:t=2",
                ],
                "badge",
            )

        speed: float | None = None
        if options.speed_tweak:
            speed = self.random.uniform(0.99, 1.01)
            if abs(speed - 1.0) < 0.0001:
                speed = 1.001
            chain([f"setpts=PTS/{speed:.5f}"], "speed")

        has_video_filter = bool(graph)
        if has_video_filter:
            chain(
                [
                    "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "setsar=1",
                    "format=yuv420p",
                ],
                "out",
            )

        audio_label: str | None = None
        if speed is not None and media.has_audio:
            audio_label = label("audio")
            graph.append(f"[0:a:0]atempo={speed:.5f}[{audio_label}]")
        return graph, current, audio_label, has_video_filter, speed

    def _select_sticker(self) -> Path | None:
        return self._select_png_asset(
            self.sticker_directory,
            resource_name="贴纸",
            optional=not self._sticker_directory_configured,
        )

    def _select_border(self) -> Path:
        selected = self._select_png_asset(
            self.border_directory,
            resource_name="边框",
            optional=False,
        )
        assert selected is not None
        return selected

    def _select_png_asset(
        self,
        directory: Path,
        *,
        resource_name: str,
        optional: bool,
    ) -> Path | None:
        try:
            root = directory.expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            if optional:
                return None
            raise DeduplicationError(f"{resource_name}资源目录不存在") from exc
        if not root.is_dir():
            raise DeduplicationError(f"{resource_name}资源路径不是目录")

        candidates: list[Path] = []
        for candidate in root.iterdir():
            if candidate.suffix.lower() != ".png":
                continue
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, RuntimeError, ValueError):
                continue
            if candidate.is_symlink() or not resolved.is_file() or resolved.suffix.lower() != ".png":
                continue
            candidates.append(resolved)
        candidates.sort(key=lambda item: item.name)
        if not candidates:
            if optional:
                return None
            raise DeduplicationError(f"{resource_name}资源目录中没有可用的 PNG 文件")
        return self.random.choice(candidates)

    def _normalize_options(self, options: DeduplicationOptions | Mapping[str, Any]) -> _Options:
        if options is None:
            raise DeduplicationError("去重参数不能为空", code="INVALID_REQUEST")

        def read(name: str, default: Any) -> Any:
            if isinstance(options, Mapping):
                return options.get(name, default)
            return getattr(options, name, default)

        values: dict[str, Any] = {}
        defaults = _Options()
        for name in (
            "change_file_hash",
            "reencode",
            "color_noise_tweak",
            "sticker",
            "subtitle_mask",
            "crop_scale",
            "mirror",
            "speed_tweak",
        ):
            value = read(name, getattr(defaults, name))
            if not isinstance(value, bool):
                raise DeduplicationError(f"{name} 必须是布尔值", code="INVALID_REQUEST")
            values[name] = value

        border_mode = read("border_mode", defaults.border_mode)
        if border_mode not in {"none", "solid", "blurred", "asset"}:
            raise DeduplicationError(
                "border_mode 必须是 none、solid、blurred 或 asset",
                code="INVALID_REQUEST",
            )
        values["border_mode"] = border_mode
        return _Options(**values)

    def _run(self, command: Sequence[str]) -> Any:
        # Explicit shell=False documents and enforces that paths and filter
        # expressions remain individual argv elements.
        return self.runner(
            list(command),
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=(
                self.probe_timeout
                if str(command[0]) == self.ffprobe_binary
                else self.process_timeout
            ),
        )

    def _temporary_output(self, destination: Path, token: str) -> Path:
        return destination.with_name(
            f".{destination.stem}.{token[:16]}.part{destination.suffix.lower()}"
        )

    def _random_hex(self, byte_count: int) -> str:
        if hasattr(self.random, "getrandbits"):
            return f"{self.random.getrandbits(byte_count * 8):0{byte_count * 2}x}"
        return secrets.token_hex(byte_count)

    @staticmethod
    def _subtitle_region(media: MediaInfo) -> tuple[int, int, int, int]:
        portrait = media.height > media.width
        x_ratio, y_ratio, width_ratio, height_ratio = (
            (0.08, 0.79, 0.84, 0.16) if portrait else (0.10, 0.78, 0.80, 0.14)
        )
        x = int(media.width * x_ratio)
        y = int(media.height * y_ratio)
        width = min(media.width - x, max(2, int(media.width * width_ratio)))
        height = min(media.height - y, max(2, int(media.height * height_ratio)))
        return x, y, width, height

    @staticmethod
    def _even(value: int) -> int:
        return max(2, int(value) - (int(value) % 2))

    @staticmethod
    def _safe_stderr(stderr: Any) -> str:
        if not stderr:
            return ""
        text = " ".join(str(stderr).strip().split())
        return text[-500:]

    @staticmethod
    def _emit(callback: ProgressCallback | None, progress: int, message: str) -> None:
        if callback is None:
            return
        try:
            callback(progress, message)
        except Exception:
            # UI/progress reporting must not make a successful media job fail.
            return


def apply_direct_deduplication(
    input_path: str,
    output_path: str,
    options: DeduplicationOptions | Mapping[str, Any],
    *,
    progress_callback: ProgressCallback | None = None,
) -> str:
    """Process one video and return the normalized absolute output path."""

    return DeduplicationService().apply(
        input_path,
        output_path,
        options,
        progress_callback=progress_callback,
    )


__all__ = [
    "DeduplicationError",
    "DeduplicationOptions",
    "DeduplicationService",
    "MediaInfo",
    "apply_direct_deduplication",
]
