"""Artifact download route."""

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.dependencies import AppServices, BackendError, get_app_services
from app.models.batch_schema import Error

router = APIRouter(tags=["Artifacts"])


@router.get(
    "/artifacts/{artifact_id}/download",
    operation_id="downloadArtifact",
    response_class=StreamingResponse,
    summary="下载处理后的视频",
    responses={
        200: {
            "description": "视频文件",
            "content": {
                "video/mp4": {"schema": {"type": "string", "format": "binary"}},
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                },
            },
        },
        404: {"model": Error, "description": "产物不存在"},
    },
)
async def download_artifact(
    artifact_id: UUID,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> StreamingResponse:
    opened = services.artifact_service.open_artifact(str(artifact_id))
    if opened is None:
        raise BackendError("ARTIFACT_NOT_FOUND", "Artifact not found", 404)

    artifact = opened.record

    async def chunks():
        # Keep the identity-checked descriptor open for the entire response.
        # Reading a local file in bounded chunks avoids the synchronous
        # iterator/thread-pool deadlock seen by ASGI clients during downloads.
        with opened:
            while data := opened.stream.read(1024 * 1024):
                yield data

    return StreamingResponse(
        chunks(),
        media_type=artifact.media_type or "application/octet-stream",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(artifact.file_name, safe='')}"
            )
        },
    )
