"""Controlled registration and lookup of generated output artifacts."""

from __future__ import annotations

import mimetypes
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import BinaryIO, Iterable
from uuid import UUID, uuid4


class ArtifactServiceError(Exception):
    """A safe artifact/path error suitable for the HTTP error mapper."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    id: UUID
    path: Path
    file_name: str
    media_type: str
    device: int
    inode: int


@dataclass(slots=True)
class OpenedArtifact:
    """An artifact whose validated file descriptor remains open for streaming."""

    record: ArtifactRecord
    stream: BinaryIO

    def close(self) -> None:
        self.stream.close()

    def __enter__(self) -> "OpenedArtifact":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


class ArtifactService:
    """Map opaque artifact IDs to regular files under configured roots."""

    def __init__(
        self,
        allowed_output_roots: Iterable[str | os.PathLike[str]] | None = None,
    ) -> None:
        configured = (
            (Path("storage") / "outputs",)
            if allowed_output_roots is None
            else tuple(allowed_output_roots)
        )
        if not configured:
            raise ValueError("allowed_output_roots cannot be empty")

        roots: list[Path] = []
        for configured_root in configured:
            root = Path(configured_root).expanduser()
            root.mkdir(parents=True, exist_ok=True)
            resolved = root.resolve(strict=True)
            if not resolved.is_dir():
                raise ValueError(f"Allowed output root is not a directory: {resolved}")
            roots.append(resolved)
        self._allowed_roots = tuple(dict.fromkeys(roots))
        self._artifacts: dict[UUID, ArtifactRecord] = {}
        self._lock = RLock()

    @property
    def allowed_output_roots(self) -> tuple[Path, ...]:
        return self._allowed_roots

    def resolve_output_directory(
        self, output_directory: str | os.PathLike[str], *, create: bool = True
    ) -> Path:
        """Validate an API-provided directory against the output allow-list."""

        raw = str(output_directory).strip()
        if not raw:
            raise self._path_error("Output directory cannot be empty")
        candidate_input = Path(raw).expanduser()
        if ".." in candidate_input.parts:
            raise self._path_error("Output directory traversal is not allowed")

        candidate = candidate_input.resolve(strict=False)
        if not self._is_within_allowed_root(candidate):
            raise self._path_error("Output directory is outside the allowed roots")
        if candidate.exists() and not candidate.is_dir():
            raise self._path_error("Output path is not a directory")

        if create:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise self._path_error("Output directory cannot be created") from exc
        if not candidate.exists() or not candidate.is_dir():
            raise self._path_error("Output directory does not exist")

        # Resolve again after creation to catch symlinks introduced in the path.
        candidate = candidate.resolve(strict=True)
        if not self._is_within_allowed_root(candidate):
            raise self._path_error("Output directory is outside the allowed roots")
        if not os.access(candidate, os.W_OK | os.X_OK):
            raise self._path_error("Output directory is not writable")
        return candidate

    def register(
        self,
        path: str | os.PathLike[str],
        file_name: str | None = None,
        media_type: str | None = None,
    ) -> ArtifactRecord:
        """Register a completed regular file and return its opaque record."""

        try:
            resolved, descriptor, file_stat = self._open_validated_file(path)
        except OSError as exc:
            raise self._path_error("Artifact file cannot be opened safely") from exc
        else:
            os.close(descriptor)
        safe_name = self._safe_file_name(file_name or resolved.name)
        resolved_media_type = media_type or mimetypes.guess_type(safe_name)[0]
        if not resolved_media_type:
            resolved_media_type = "application/octet-stream"
        artifact = ArtifactRecord(
            id=uuid4(),
            path=resolved,
            file_name=safe_name,
            media_type=resolved_media_type,
            device=file_stat.st_dev,
            inode=file_stat.st_ino,
        )
        with self._lock:
            self._artifacts[artifact.id] = artifact
        return artifact

    def get_artifact(self, artifact_id: UUID | str) -> ArtifactRecord | None:
        """Return a record only while the path still names its registered inode."""

        opened = self.open_artifact(artifact_id)
        if opened is None:
            return None
        try:
            return opened.record
        finally:
            opened.close()

    def open_artifact(self, artifact_id: UUID | str) -> OpenedArtifact | None:
        """Open and identity-check an artifact, keeping the safe FD alive.

        The caller must close the returned handle.  Holding the descriptor for
        the whole response prevents a path replacement after validation from
        redirecting a download to a different file.
        """

        normalized = self._parse_uuid(artifact_id)
        if normalized is None:
            return None
        with self._lock:
            artifact = self._artifacts.get(normalized)
        if artifact is None:
            return None
        try:
            current_path, descriptor, file_stat = self._open_validated_file(
                artifact.path,
                expected_identity=(artifact.device, artifact.inode),
            )
        except (ArtifactServiceError, OSError):
            return None
        record = ArtifactRecord(
            id=artifact.id,
            path=current_path,
            file_name=artifact.file_name,
            media_type=artifact.media_type,
            device=file_stat.st_dev,
            inode=file_stat.st_ino,
        )
        try:
            stream = os.fdopen(descriptor, "rb", closefd=True)
        except Exception:
            os.close(descriptor)
            raise
        return OpenedArtifact(record=record, stream=stream)

    def _open_validated_file(
        self,
        path: str | os.PathLike[str],
        *,
        expected_identity: tuple[int, int] | None = None,
    ) -> tuple[Path, int, os.stat_result]:
        raw_path = Path(path).expanduser()
        try:
            if raw_path.is_symlink():
                raise self._path_error("Artifact path cannot be a symbolic link")
            resolved = raw_path.resolve(strict=True)
        except ArtifactServiceError:
            raise
        except (OSError, RuntimeError) as exc:
            raise self._path_error("Artifact file does not exist") from exc
        if not self._is_within_allowed_root(resolved):
            raise self._path_error("Artifact path is outside the allowed roots")

        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(resolved, flags)
        except OSError as exc:
            raise self._path_error("Artifact file cannot be opened safely") from exc

        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode):
                raise self._path_error("Artifact path is not a regular file")

            # Re-resolve and lstat after opening.  Comparing the path identity
            # with fstat catches final-component and parent-directory swaps
            # that happen while the file is being opened.
            current_path = raw_path.resolve(strict=True)
            if not self._is_within_allowed_root(current_path):
                raise self._path_error("Artifact path is outside the allowed roots")
            path_stat = os.stat(current_path, follow_symlinks=False)
            current_identity = (file_stat.st_dev, file_stat.st_ino)
            if (path_stat.st_dev, path_stat.st_ino) != current_identity:
                raise self._path_error("Artifact path changed during validation")
            if expected_identity is not None and current_identity != expected_identity:
                raise self._path_error("Artifact file no longer matches its registration")
            return current_path, descriptor, file_stat
        except Exception:
            os.close(descriptor)
            raise

    def _is_within_allowed_root(self, path: Path) -> bool:
        return any(path == root or path.is_relative_to(root) for root in self._allowed_roots)

    @staticmethod
    def _safe_file_name(value: str) -> str:
        name = str(value).replace("\\", "/").rsplit("/", 1)[-1]
        name = "".join(char for char in name if char >= " " and char != "\x7f")
        name = name.strip().strip(".")
        if not name:
            return "artifact"
        return name[:255]

    @staticmethod
    def _parse_uuid(value: UUID | str) -> UUID | None:
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (TypeError, ValueError, AttributeError):
            return None

    @staticmethod
    def _path_error(message: str) -> ArtifactServiceError:
        return ArtifactServiceError("OUTPUT_PATH_NOT_ALLOWED", message, 400)


__all__ = [
    "ArtifactRecord",
    "ArtifactService",
    "ArtifactServiceError",
    "OpenedArtifact",
]
