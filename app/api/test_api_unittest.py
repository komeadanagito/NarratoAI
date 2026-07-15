from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import httpx

from app.api.dependencies import AppServices
from app.api.main import create_app
from app.models.batch_schema import Batch, Upload, VideoJob


class _UploadService:
    def __init__(self, upload_id):
        self.upload_id = upload_id

    async def save_uploads(self, files):
        return [
            Upload(
                id=self.upload_id,
                file_name=files[0].filename,
                size_bytes=3,
            )
        ]


class _BatchProcessor:
    def __init__(self, batch):
        self.batch = batch
        self.shutdown_called = False
        self.last_request = None

    def create_batch(self, request):
        self.last_request = request
        return self.batch

    def shutdown(self):
        self.shutdown_called = True


class _BatchStore:
    def __init__(self, batch):
        self.batch = batch

    def get_batch(self, batch_id):
        if batch_id == str(self.batch.id):
            return self.batch
        return None


class _ArtifactService:
    def __init__(self, artifact_id, path):
        self.artifact_id = artifact_id
        self.path = path

    def get_artifact(self, artifact_id):
        if artifact_id != str(self.artifact_id):
            return None
        return type(
            "Artifact",
            (),
            {
                "path": self.path,
                "file_name": "result.mp4",
                "media_type": "video/mp4",
            },
        )()


class BatchApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output = Path(self.temp_dir.name) / "result.mp4"
        self.output.write_bytes(b"video")
        self.upload_id = uuid4()
        self.batch_id = uuid4()
        self.artifact_id = uuid4()
        self.batch = Batch(
            id=self.batch_id,
            status="queued",
            progress=0,
            total=1,
            succeeded=0,
            failed=0,
            jobs=[
                VideoJob(
                    id=uuid4(),
                    upload_id=self.upload_id,
                    file_name="source.mp4",
                    status="queued",
                    stage="queued",
                    progress=0,
                )
            ],
        )
        self.processor = _BatchProcessor(self.batch)
        services = AppServices(
            upload_service=_UploadService(self.upload_id),
            batch_processor=self.processor,
            batch_store=_BatchStore(self.batch),
            artifact_service=_ArtifactService(self.artifact_id, self.output),
        )
        self.app = create_app(services)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)
        self.temp_dir.cleanup()

    async def test_complete_upload_batch_poll_and_download_flow(self):
        health = await self.client.get("/api/v1/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ok"})

        upload = await self.client.post(
            "/api/v1/uploads/videos",
            files={"files": ("source.mp4", b"raw", "video/mp4")},
        )
        self.assertEqual(upload.status_code, 201)
        self.assertEqual(upload.json()["uploads"][0]["id"], str(self.upload_id))

        created = await self.client.post(
            "/api/v1/batches",
            json={
                "upload_ids": [str(self.upload_id)],
                "output_directory": "./storage/outputs",
            },
        )
        self.assertEqual(created.status_code, 202)
        self.assertEqual(created.json()["batch"]["id"], str(self.batch_id))
        self.assertNotIn("message", created.json()["batch"]["jobs"][0])

        polled = await self.client.get(f"/api/v1/batches/{self.batch_id}")
        self.assertEqual(polled.status_code, 200)
        self.assertEqual(polled.json(), created.json())

        downloaded = await self.client.get(
            f"/api/v1/artifacts/{self.artifact_id}/download"
        )
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.headers["content-type"], "video/mp4")
        self.assertEqual(downloaded.content, b"video")

    async def test_errors_are_strict_and_validation_uses_400(self):
        missing_batch = await self.client.get(f"/api/v1/batches/{uuid4()}")
        self.assertEqual(missing_batch.status_code, 404)
        self.assertEqual(
            missing_batch.json(),
            {"code": "BATCH_NOT_FOUND", "message": "Batch not found"},
        )

        missing_artifact = await self.client.get(
            f"/api/v1/artifacts/{uuid4()}/download"
        )
        self.assertEqual(missing_artifact.status_code, 404)
        self.assertEqual(set(missing_artifact.json()), {"code", "message"})

        invalid = await self.client.post(
            "/api/v1/batches",
            json={"upload_ids": [], "output_directory": "x", "unknown": True},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(
            invalid.json(),
            {"code": "INVALID_REQUEST", "message": "Invalid request"},
        )

    async def test_concurrency_has_no_upper_bound_and_request_types_are_strict(self):
        accepted = await self.client.post(
            "/api/v1/batches",
            json={
                "upload_ids": [str(self.upload_id)],
                "output_directory": "./storage/outputs",
                "concurrency": 1000,
                "narration": {"enabled": False},
                "deduplication": {"reencode": True},
            },
        )
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(self.processor.last_request.concurrency, 1000)

        invalid_values = [
            {"concurrency": 0},
            {"concurrency": True},
            {"concurrency": "2"},
            {"narration": {"enabled": "false"}},
            {"deduplication": {"reencode": "false"}},
        ]
        for invalid_fields in invalid_values:
            with self.subTest(payload=invalid_fields):
                response = await self.client.post(
                    "/api/v1/batches",
                    json={
                        "upload_ids": [str(self.upload_id)],
                        "output_directory": "./storage/outputs",
                        **invalid_fields,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json(),
                    {"code": "INVALID_REQUEST", "message": "Invalid request"},
                )

    def test_openapi_operation_ids_and_documented_status_codes(self):
        schema = self.app.openapi()
        operations = {
            (path.removeprefix("/api/v1"), method): operation["operationId"]
            for path, path_item in schema["paths"].items()
            for method, operation in path_item.items()
            if method in {"get", "post"}
        }
        self.assertEqual(
            operations,
            {
                ("/health", "get"): "getHealth",
                ("/uploads/videos", "post"): "uploadVideos",
                ("/batches", "post"): "createBatch",
                ("/batches/{batch_id}", "get"): "getBatch",
                ("/artifacts/{artifact_id}/download", "get"): "downloadArtifact",
            },
        )
        for path_item in schema["paths"].values():
            for method, operation in path_item.items():
                if method in {"get", "post"}:
                    self.assertNotIn("422", operation["responses"])

        concurrency_schema = schema["components"]["schemas"]["BatchCreateRequest"][
            "properties"
        ]["concurrency"]
        self.assertEqual(concurrency_schema["minimum"], 1)
        self.assertNotIn("maximum", concurrency_schema)


if __name__ == "__main__":
    unittest.main()
