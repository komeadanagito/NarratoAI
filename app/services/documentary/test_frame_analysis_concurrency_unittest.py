import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from app.services.documentary.frame_analysis_service import DocumentaryFrameAnalysisService


def test_same_video_keyframe_extraction_is_serialized(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    calls = 0
    calls_lock = Lock()

    class FakeProcessor:
        def __init__(self, _video_path):
            pass

        def extract_frames_by_interval_with_fallback(self, output_dir, interval_seconds):
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.05)
            frame = Path(output_dir) / "keyframe_000001_000000000.jpg"
            frame.write_bytes(b"jpg")
            return [str(frame)]

    monkeypatch.setattr(
        "app.services.documentary.frame_analysis_service.utils.temp_dir",
        lambda: str(tmp_path / "temp"),
    )
    monkeypatch.setattr(
        "app.services.documentary.frame_analysis_service.video_processor.VideoProcessor",
        FakeProcessor,
    )
    service = DocumentaryFrameAnalysisService()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(service._load_or_extract_keyframes, str(source), 3.0)
            for _ in range(2)
        ]
        results = [future.result() for future in futures]

    assert calls == 1
    assert results[0] == results[1]
