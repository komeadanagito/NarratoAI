"""Real FFmpeg smoke test for the public upload-to-download workflow."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import httpx

from app.api.dependencies import AppServices
from app.api.main import create_app
from app.services.artifact_service import ArtifactService
from app.services.batch_processor import BatchProcessor
from app.services.batch_store import BatchStore
from app.services.deduplication_service import DeduplicationService
from app.services.upload_service import UploadService


pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="FFmpeg and FFprobe are required",
)


@pytest.mark.anyio
async def test_real_media_upload_process_poll_and_download(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    generated = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x120:r=12:d=0.6",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=24000:duration=0.6",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert generated.returncode == 0, generated.stderr

    output_root = tmp_path / "outputs"
    upload_service = UploadService(tmp_path / "uploads", max_file_size=10 * 1024 * 1024)
    store = BatchStore()
    artifacts = ArtifactService([output_root])
    processor = BatchProcessor(
        upload_service=upload_service,
        batch_store=store,
        artifact_service=artifacts,
        deduplication_service=DeduplicationService(ffmpeg_threads=1),
        max_workers=1,
        queue_capacity=2,
    )
    services = AppServices(upload_service, processor, store, artifacts)

    application = create_app(services)
    lifespan = application.router.lifespan_context(application)
    await lifespan.__aenter__()
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://test",
    )
    try:
        upload = await asyncio.wait_for(
            client.post(
                "/api/v1/uploads/videos",
                files={"files": (source.name, source.read_bytes(), "video/mp4")},
            ),
            timeout=5,
        )
        assert upload.status_code == 201, upload.text
        upload_id = upload.json()["uploads"][0]["id"]

        created = await asyncio.wait_for(
            client.post(
                "/api/v1/batches",
                json={
                    "upload_ids": [upload_id],
                    "output_directory": str(output_root),
                    "concurrency": 1,
                    "narration": {"enabled": False},
                    "deduplication": {
                        "change_file_hash": True,
                        "reencode": True,
                        "color_noise_tweak": True,
                        "sticker": True,
                        "speed_tweak": True,
                    },
                },
            ),
            timeout=5,
        )
        assert created.status_code == 202, created.text
        batch_id = created.json()["batch"]["id"]

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            polled = await asyncio.wait_for(
                client.get(f"/api/v1/batches/{batch_id}"),
                timeout=5,
            )
            assert polled.status_code == 200
            batch = polled.json()["batch"]
            if batch["status"] in {"succeeded", "partially_succeeded", "failed"}:
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("real media batch did not finish")

        assert batch["status"] == "succeeded", batch
        job = batch["jobs"][0]
        assert Path(job["output_path"]).is_file()
        downloaded = await asyncio.wait_for(
            client.get(f"/api/v1/artifacts/{job['artifact_id']}/download"),
            timeout=5,
        )
        assert downloaded.status_code == 200
        assert downloaded.content

        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0",
                job["output_path"],
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        assert probe.returncode == 0, probe.stderr
        assert probe.stdout.strip() == "160,120"
    finally:
        await client.aclose()
        await asyncio.wait_for(lifespan.__aexit__(None, None, None), timeout=5)
