"""Secure, streaming storage for uploaded video files."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import UUID, uuid4

from app.models.batch_schema import Upload


class AsyncUpload(Protocol):
    """The subset of FastAPI's ``UploadFile`` used by this service."""

    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...


class UploadServiceError(Exception):
    """A safe upload error that can be mapped directly to an API response."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class StoredUpload:
    """Private upload metadata; ``stored_path`` is never part of the API model."""

    id: UUID
    file_name: str
    size_bytes: int
    stored_path: Path
    extension: str
    media_info: Mapping[str, Any]

    def to_public(self) -> Upload:
        return Upload(id=self.id, file_name=self.file_name, size_bytes=self.size_bytes)


MediaProbe = Callable[[Path], Mapping[str, Any] | bool]
SignatureValidator = Callable[[Path, str], bool]


class UploadService:
    """Save multipart uploads without loading complete files into memory.

    Each file is written below ``{upload_root}/{uuid}/source.{ext}``.  A
    temporary ``.part`` file is validated before an atomic rename makes it
    visible to the rest of the application.
    """

    _KNOWN_SIGNATURE_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".webm"})

    def __init__(
        self,
        upload_root: str | os.PathLike[str],
        *,
        max_file_size: int = 2 * 1024 * 1024 * 1024,
        allowed_extensions: Sequence[str] = (".mp4", ".mov"),
        chunk_size: int = 1024 * 1024,
        media_probe: MediaProbe | None = None,
        signature_validator: SignatureValidator | None = None,
    ) -> None:
        if max_file_size < 1:
            raise ValueError("max_file_size must be positive")
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")

        extensions = frozenset(self._normalize_extension(ext) for ext in allowed_extensions)
        if not extensions:
            raise ValueError("allowed_extensions cannot be empty")
        if signature_validator is None:
            unknown = extensions - self._KNOWN_SIGNATURE_EXTENSIONS
            if unknown:
                raise ValueError(
                    "A signature_validator is required for extensions: "
                    + ", ".join(sorted(unknown))
                )

        root = Path(upload_root).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        self._upload_root = root.resolve(strict=True)
        if not self._upload_root.is_dir():
            raise ValueError("upload_root must be a directory")

        self.max_file_size = max_file_size
        self.allowed_extensions = extensions
        self.chunk_size = chunk_size
        self._media_probe = media_probe or self._ffprobe_video
        self._signature_validator = signature_validator or self._has_video_signature
        self._uploads: dict[UUID, StoredUpload] = {}
        self._lock = RLock()

    @property
    def upload_root(self) -> Path:
        return self._upload_root

    async def save_uploads(self, files: Sequence[AsyncUpload]) -> list[Upload]:
        """Stream, validate and register all files in one request.

        Registration is transactional for the request: if any file fails,
        files already written by this call are removed and no IDs are exposed.
        """

        if not files:
            raise UploadServiceError("INVALID_REQUEST", "At least one file is required", 400)

        pending: list[StoredUpload] = []
        created_directories: list[Path] = []
        try:
            for upload_file in files:
                record, directory = await self._save_one(upload_file)
                pending.append(record)
                created_directories.append(directory)

            with self._lock:
                self._uploads.update({record.id: record for record in pending})
            return [record.to_public() for record in pending]
        except BaseException:
            for directory in created_directories:
                shutil.rmtree(directory, ignore_errors=True)
            raise

    def get_upload(self, upload_id: UUID | str) -> StoredUpload | None:
        """Return an immutable private record for an upload ID, if registered."""

        normalized = self._parse_uuid(upload_id)
        if normalized is None:
            return None
        with self._lock:
            record = self._uploads.get(normalized)
            if record is None:
                return None
            return StoredUpload(
                id=record.id,
                file_name=record.file_name,
                size_bytes=record.size_bytes,
                stored_path=record.stored_path,
                extension=record.extension,
                media_info=deepcopy(dict(record.media_info)),
            )

    async def _save_one(self, upload_file: AsyncUpload) -> tuple[StoredUpload, Path]:
        original_name = str(getattr(upload_file, "filename", "") or "")
        extension = Path(original_name.replace("\\", "/")).suffix.lower()
        if extension not in self.allowed_extensions:
            raise UploadServiceError(
                "UNSUPPORTED_MEDIA",
                f"Unsupported video extension: {extension or '(none)'}",
                400,
            )

        upload_id, directory = self._create_upload_directory()
        target_path = directory / f"source{extension}"
        part_path = directory / f"source{extension}.part"
        size_bytes = 0

        try:
            with part_path.open("xb") as output:
                while True:
                    chunk = await upload_file.read(self.chunk_size)
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes):
                        raise UploadServiceError(
                            "INVALID_REQUEST", "Uploaded file returned invalid data", 400
                        )
                    size_bytes += len(chunk)
                    if size_bytes > self.max_file_size:
                        raise UploadServiceError(
                            "FILE_TOO_LARGE", "Uploaded file exceeds the size limit", 413
                        )
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())

            if size_bytes == 0:
                raise UploadServiceError("UNSUPPORTED_MEDIA", "Uploaded video is empty", 400)
            if not self._signature_validator(part_path, extension):
                raise UploadServiceError(
                    "UNSUPPORTED_MEDIA", "Uploaded file signature is not a supported video", 400
                )

            try:
                probe_result = self._media_probe(part_path)
            except UploadServiceError:
                raise
            except Exception as exc:
                raise UploadServiceError(
                    "UNSUPPORTED_MEDIA", "Uploaded file is not a valid video", 400
                ) from exc
            if probe_result is False:
                raise UploadServiceError(
                    "UNSUPPORTED_MEDIA", "Uploaded file is not a valid video", 400
                )
            media_info: Mapping[str, Any]
            if probe_result is True:
                media_info = {}
            elif isinstance(probe_result, Mapping):
                media_info = deepcopy(dict(probe_result))
            else:
                raise UploadServiceError(
                    "UNSUPPORTED_MEDIA", "Uploaded file is not a valid video", 400
                )

            os.replace(part_path, target_path)
            record = StoredUpload(
                id=upload_id,
                file_name=self._safe_display_name(original_name, extension),
                size_bytes=size_bytes,
                stored_path=target_path,
                extension=extension,
                media_info=media_info,
            )
            return record, directory
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def _create_upload_directory(self) -> tuple[UUID, Path]:
        while True:
            upload_id = uuid4()
            directory = self._upload_root / str(upload_id)
            try:
                directory.mkdir(mode=0o700)
            except FileExistsError:
                continue
            return upload_id, directory

    @staticmethod
    def _normalize_extension(extension: str) -> str:
        value = str(extension).strip().lower()
        if not value:
            raise ValueError("Empty file extension")
        if not value.startswith("."):
            value = f".{value}"
        if not re.fullmatch(r"\.[a-z0-9]+", value):
            raise ValueError(f"Invalid file extension: {extension}")
        return value

    @staticmethod
    def _safe_display_name(filename: str, extension: str) -> str:
        basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        basename = "".join(char for char in basename if char >= " " and char != "\x7f")
        basename = basename.strip().strip(".")
        if not basename or Path(basename).suffix.lower() != extension:
            basename = f"video{extension}"
        if len(basename) > 255:
            stem = Path(basename).stem[: 255 - len(extension)] or "video"
            basename = f"{stem}{extension}"
        return basename

    @staticmethod
    def _has_video_signature(path: Path, extension: str) -> bool:
        with path.open("rb") as source:
            header = source.read(4096)
        if extension in {".mp4", ".mov"}:
            # ISO Base Media/QuickTime files normally expose an ftyp box near
            # the start. ffprobe below performs the authoritative parse.
            return b"ftyp" in header[4:64]
        if extension in {".mkv", ".webm"}:
            return header.startswith(b"\x1aE\xdf\xa3")
        return False

    @staticmethod
    def _ffprobe_video(path: Path) -> Mapping[str, Any]:
        command = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=index,codec_type,codec_name,width,height:format=format_name,duration",
            "-of",
            "json",
            os.fspath(path),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("ffprobe could not inspect the uploaded file") from exc
        if result.returncode != 0:
            raise RuntimeError("ffprobe rejected the uploaded file")
        try:
            payload = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("ffprobe returned invalid metadata") from exc
        streams = payload.get("streams")
        if not isinstance(streams, list) or not streams:
            raise RuntimeError("ffprobe did not find a video stream")
        if not any(stream.get("codec_type") == "video" for stream in streams):
            raise RuntimeError("ffprobe did not find a video stream")
        return payload

    @staticmethod
    def _parse_uuid(value: UUID | str) -> UUID | None:
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (TypeError, ValueError, AttributeError):
            return None


__all__ = ["StoredUpload", "UploadService", "UploadServiceError"]
