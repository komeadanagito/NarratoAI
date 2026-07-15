"""Video upload routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.api.dependencies import AppServices, get_app_services
from app.models.batch_schema import Error, UploadsResponse

router = APIRouter(tags=["Uploads"])


@router.post(
    "/uploads/videos",
    operation_id="uploadVideos",
    response_model=UploadsResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    summary="批量上传视频",
    responses={
        400: {"model": Error, "description": "请求失败"},
        413: {"model": Error, "description": "文件超过上限"},
    },
)
async def upload_videos(
    files: Annotated[list[UploadFile], File(min_length=1)],
    services: Annotated[AppServices, Depends(get_app_services)],
) -> UploadsResponse:
    uploads = await services.upload_service.save_uploads(files)
    return UploadsResponse(uploads=uploads)
