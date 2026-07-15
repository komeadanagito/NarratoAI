from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.services.upload_service import UploadService, UploadServiceError


MP4_BYTES = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + (b"x" * 80)


class FakeUpload:
    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self._data = data
        self._offset = 0
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self._offset >= len(self._data):
            return b""
        end = len(self._data) if size < 0 else self._offset + size
        chunk = self._data[self._offset : end]
        self._offset += len(chunk)
        await asyncio.sleep(0)
        return chunk


class UploadServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "uploads"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def make_service(self, **kwargs: object) -> UploadService:
        return UploadService(
            self.root,
            chunk_size=7,
            media_probe=lambda path: {"path_at_probe": path.name, "video": True},
            **kwargs,
        )

    async def test_streams_to_uuid_path_and_returns_public_model(self) -> None:
        upload_file = FakeUpload("../../unsafe name.mp4", MP4_BYTES)
        service = self.make_service()

        uploads = await service.save_uploads([upload_file])

        self.assertEqual(len(uploads), 1)
        public = uploads[0]
        self.assertEqual(public.file_name, "unsafe name.mp4")
        self.assertEqual(public.size_bytes, len(MP4_BYTES))
        self.assertNotIn("stored_path", public.model_dump())
        self.assertTrue(all(size == 7 for size in upload_file.read_sizes))

        stored = service.get_upload(str(public.id))
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.stored_path, self.root.resolve() / str(public.id) / "source.mp4")
        self.assertEqual(stored.stored_path.read_bytes(), MP4_BYTES)
        self.assertEqual(stored.media_info["path_at_probe"], "source.mp4.part")
        self.assertFalse(any(self.root.rglob("*.part")))

    async def test_rejects_unsupported_extension_before_creating_files(self) -> None:
        service = self.make_service()

        with self.assertRaises(UploadServiceError) as raised:
            await service.save_uploads([FakeUpload("clip.exe", MP4_BYTES)])

        self.assertEqual(raised.exception.code, "UNSUPPORTED_MEDIA")
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(list(self.root.iterdir()), [])

    async def test_stops_at_size_limit_and_cleans_partial_file(self) -> None:
        probe_calls = 0

        def probe(_path: Path) -> bool:
            nonlocal probe_calls
            probe_calls += 1
            return True

        service = UploadService(
            self.root,
            max_file_size=20,
            chunk_size=6,
            media_probe=probe,
        )
        upload_file = FakeUpload("large.mp4", MP4_BYTES)

        with self.assertRaises(UploadServiceError) as raised:
            await service.save_uploads([upload_file])

        self.assertEqual(raised.exception.code, "FILE_TOO_LARGE")
        self.assertEqual(raised.exception.status_code, 413)
        self.assertLess(sum(upload_file.read_sizes), len(MP4_BYTES) * 2)
        self.assertEqual(probe_calls, 0)
        self.assertEqual(list(self.root.iterdir()), [])

    async def test_rejects_forged_signature_and_failed_probe(self) -> None:
        service = self.make_service()
        with self.assertRaises(UploadServiceError) as signature_error:
            await service.save_uploads([FakeUpload("fake.mp4", b"not a video")])
        self.assertEqual(signature_error.exception.code, "UNSUPPORTED_MEDIA")

        service = UploadService(self.root, media_probe=lambda _path: False)
        with self.assertRaises(UploadServiceError) as probe_error:
            await service.save_uploads([FakeUpload("broken.mov", MP4_BYTES)])
        self.assertEqual(probe_error.exception.code, "UNSUPPORTED_MEDIA")
        self.assertEqual(list(self.root.iterdir()), [])

    async def test_multi_file_request_rolls_back_earlier_files(self) -> None:
        service = self.make_service()

        with self.assertRaises(UploadServiceError):
            await service.save_uploads(
                [FakeUpload("valid.mp4", MP4_BYTES), FakeUpload("invalid.txt", b"text")]
            )

        self.assertEqual(list(self.root.iterdir()), [])

    async def test_concurrent_uploads_get_distinct_paths_and_records(self) -> None:
        service = self.make_service()
        results = await asyncio.gather(
            *(service.save_uploads([FakeUpload("same.mp4", MP4_BYTES)]) for _ in range(12))
        )

        identifiers = {batch[0].id for batch in results}
        self.assertEqual(len(identifiers), 12)
        for identifier in identifiers:
            stored = service.get_upload(identifier)
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertTrue(stored.stored_path.is_file())

    async def test_empty_file_list_and_empty_file_are_rejected(self) -> None:
        service = self.make_service()
        with self.assertRaises(UploadServiceError) as no_files:
            await service.save_uploads([])
        self.assertEqual(no_files.exception.code, "INVALID_REQUEST")

        with self.assertRaises(UploadServiceError) as empty_file:
            await service.save_uploads([FakeUpload("empty.mp4", b"")])
        self.assertEqual(empty_file.exception.code, "UNSUPPORTED_MEDIA")


if __name__ == "__main__":
    unittest.main()
