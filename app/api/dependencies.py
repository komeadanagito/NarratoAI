"""Application service container and FastAPI dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request


class BackendError(Exception):
    """Safe domain exception that can be returned through the public API."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class AppServices:
    upload_service: Any
    batch_processor: Any
    batch_store: Any
    artifact_service: Any


def build_default_services() -> AppServices:
    """Build the single-process MVP service graph.

    Imports are intentionally local so importing the ASGI application does not
    initialize executors or touch the filesystem.  Service construction happens
    once during application startup.
    """

    from app.services.artifact_service import ArtifactService
    from app.services.backend_settings import BackendSettings
    from app.services.batch_processor import BatchProcessor
    from app.services.batch_store import BatchStore
    from app.services.deduplication_service import DeduplicationService
    from app.services.upload_service import UploadService

    settings = BackendSettings.load()
    upload_service = UploadService(
        settings.upload_directory,
        max_file_size=settings.max_upload_size_bytes,
        allowed_extensions=settings.allowed_video_extensions,
    )
    batch_store = BatchStore()
    artifact_service = ArtifactService(settings.allowed_output_roots)
    deduplication_service = DeduplicationService(
        ffmpeg_threads=settings.ffmpeg_threads,
        process_timeout=settings.ffmpeg_timeout_seconds,
    )
    batch_processor = BatchProcessor(
        upload_service=upload_service,
        batch_store=batch_store,
        artifact_service=artifact_service,
        deduplication_service=deduplication_service,
        queue_capacity=settings.queue_capacity,
    )
    return AppServices(
        upload_service=upload_service,
        batch_processor=batch_processor,
        batch_store=batch_store,
        artifact_service=artifact_service,
    )


async def get_app_services(request: Request) -> AppServices:
    services = getattr(request.app.state, "services", None)
    if services is None:
        raise BackendError(
            code="INTERNAL_ERROR",
            message="Application services are not initialized",
            status_code=500,
        )
    return services


__all__ = ["AppServices", "BackendError", "build_default_services", "get_app_services"]
