import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from uuid import uuid4

import pytest

from app.models.batch_schema import BatchCreateRequest, BatchStatus
from app.services.artifact_service import ArtifactService
from app.services.batch_processor import BatchProcessor, BatchProcessorError
from app.services.batch_store import BatchStore


@dataclass
class FakeUpload:
    id: object
    file_name: str
    stored_path: Path


class FakeUploads:
    def __init__(self, records):
        self.records = {record.id: record for record in records}

    def get_upload(self, upload_id):
        return self.records.get(upload_id)


class CopyTransform:
    def apply(self, input_path, output_path, _options, progress_callback=None):
        if progress_callback:
            progress_callback(50, "half")
        Path(output_path).write_bytes(Path(input_path).read_bytes())
        if progress_callback:
            progress_callback(100, "done")
        return output_path


def wait_for_batch(store, batch_id, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        batch = store.get_batch(batch_id)
        if batch.status in {
            BatchStatus.succeeded,
            BatchStatus.partially_succeeded,
            BatchStatus.failed,
        }:
            return batch
        time.sleep(0.01)
    raise AssertionError("batch did not finish")


def test_batch_processor_runs_and_registers_download(tmp_path):
    output_root = tmp_path / "outputs"
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    upload = FakeUpload(uuid4(), "示例.mp4", source)
    store = BatchStore()
    artifacts = ArtifactService([output_root])
    processor = BatchProcessor(
        upload_service=FakeUploads([upload]),
        batch_store=store,
        artifact_service=artifacts,
        deduplication_service=CopyTransform(),
        max_workers=1,
        queue_capacity=2,
    )
    try:
        batch = processor.create_batch(
            BatchCreateRequest(
                upload_ids=[upload.id],
                output_directory=str(output_root),
            )
        )
        completed = wait_for_batch(store, batch.id)
        assert completed.status == BatchStatus.succeeded
        assert completed.progress == 100
        assert completed.jobs[0].message == "处理成功了"
        assert artifacts.get_artifact(completed.jobs[0].artifact_id) is not None
    finally:
        processor.shutdown()


def test_batch_processor_rejects_missing_upload(tmp_path):
    output_root = tmp_path / "outputs"
    processor = BatchProcessor(
        upload_service=FakeUploads([]),
        batch_store=BatchStore(),
        artifact_service=ArtifactService([output_root]),
        deduplication_service=CopyTransform(),
        max_workers=1,
        queue_capacity=0,
    )
    try:
        with pytest.raises(BatchProcessorError) as error:
            processor.create_batch(
                BatchCreateRequest(
                    upload_ids=[uuid4()],
                    output_directory=str(output_root),
                )
            )
        assert error.value.status_code == 404
    finally:
        processor.shutdown()


def test_batch_processor_queue_is_bounded(tmp_path):
    output_root = tmp_path / "outputs"
    uploads = []
    for index in range(2):
        source = tmp_path / f"source-{index}.mp4"
        source.write_bytes(b"video")
        uploads.append(FakeUpload(uuid4(), source.name, source))

    store = BatchStore()
    processor = BatchProcessor(
        upload_service=FakeUploads(uploads),
        batch_store=store,
        artifact_service=ArtifactService([output_root]),
        deduplication_service=CopyTransform(),
        max_workers=1,
        queue_capacity=0,
    )
    try:
        with pytest.raises(BatchProcessorError) as error:
            processor.create_batch(
                BatchCreateRequest(
                    upload_ids=[upload.id for upload in uploads],
                    output_directory=str(output_root),
                    concurrency=1,
                )
            )
        assert error.value.status_code == 429
    finally:
        processor.shutdown()


def test_batch_processor_honors_per_batch_concurrency(tmp_path):
    output_root = tmp_path / "outputs"
    uploads = []
    for index in range(3):
        source = tmp_path / f"source-{index}.mp4"
        source.write_bytes(f"video-{index}".encode())
        uploads.append(FakeUpload(uuid4(), source.name, source))

    lock = Lock()
    active = 0
    max_active = 0

    class CountingTransform(CopyTransform):
        def apply(self, *args, **kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.03)
                return super().apply(*args, **kwargs)
            finally:
                with lock:
                    active -= 1

    store = BatchStore()
    processor = BatchProcessor(
        upload_service=FakeUploads(uploads),
        batch_store=store,
        artifact_service=ArtifactService([output_root]),
        deduplication_service=CountingTransform(),
        max_workers=3,
        queue_capacity=3,
    )
    try:
        batch = processor.create_batch(
            BatchCreateRequest(
                upload_ids=[upload.id for upload in uploads],
                output_directory=str(output_root),
                concurrency=1,
            )
        )
        assert wait_for_batch(store, batch.id).status == BatchStatus.succeeded
        assert max_active == 1
    finally:
        processor.shutdown()


def test_batch_processor_does_not_expose_internal_exception_text(tmp_path):
    output_root = tmp_path / "outputs"
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    upload = FakeUpload(uuid4(), source.name, source)

    class FailingTransform:
        def apply(self, *_args, **_kwargs):
            raise RuntimeError("secret-token at /private/internal/path")

    store = BatchStore()
    processor = BatchProcessor(
        upload_service=FakeUploads([upload]),
        batch_store=store,
        artifact_service=ArtifactService([output_root]),
        deduplication_service=FailingTransform(),
        max_workers=1,
        queue_capacity=1,
    )
    try:
        batch = processor.create_batch(
            BatchCreateRequest(upload_ids=[upload.id], output_directory=str(output_root))
        )
        failed = wait_for_batch(store, batch.id)
        assert failed.status == BatchStatus.failed
        assert failed.jobs[0].error.message == "视频处理失败"
        assert "secret-token" not in failed.jobs[0].error.message
    finally:
        processor.shutdown()
