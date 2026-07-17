import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.documentary.video_narration_service import VideoNarrationService
from app.services.llm.openai_compatible_provider import OpenAICompatibleVisionProvider


class FakeVideoProvider:
    model_name = "video-model"

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = []

    async def analyze_video(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_video_narration_service_sends_complete_video_once(tmp_path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    provider = FakeVideoProvider(
        json.dumps(
            {
                "items": [
                    {
                        "_id": 1,
                        "timestamp": "00:00:00,000-00:00:02,000",
                        "picture": "老人走进酒店",
                        "narration": "老人刚进酒店，麻烦就找上门。",
                    }
                ]
            },
            ensure_ascii=False,
        )
    )
    service = VideoNarrationService(provider=provider)

    result = asyncio.run(service.generate_narration_script(str(video), language="zh-CN"))

    assert len(provider.calls) == 1
    assert provider.calls[0]["video"] == video.resolve()
    assert provider.calls[0]["response_format"] == "json"
    assert provider.calls[0]["temperature"] == 0.2
    assert provider.calls[0]["max_tokens"] == 4096
    assert "完整视频" in provider.calls[0]["prompt"]
    assert result[0]["narration"] == "老人刚进酒店，麻烦就找上门。"


@pytest.mark.parametrize(
    "response,error",
    [
        ("", "空响应"),
        ("not-json", "合法 JSON"),
        ('{"items": []}', "非空 items"),
    ],
)
def test_video_narration_service_rejects_invalid_model_output(response, error):
    with pytest.raises(ValueError, match=error):
        VideoNarrationService.parse_response(response)


def test_openai_compatible_video_provider_builds_video_url_payload(tmp_path):
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"small-video")
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"items": [{}]}'))]
        )
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    provider = OpenAICompatibleVisionProvider(api_key="key", model_name="video-model")
    provider._build_client = lambda **_kwargs: client

    result = asyncio.run(
        provider.analyze_video(
            video,
            "生成脚本",
            system_prompt="只返回 JSON",
            response_format="json",
            video_fps=1.0,
        )
    )

    assert result == '{"items": [{}]}'
    request = create.await_args.kwargs
    assert request["response_format"] == {"type": "json_object"}
    assert request["messages"][0] == {"role": "system", "content": "只返回 JSON"}
    video_part = request["messages"][1]["content"][0]
    assert video_part["type"] == "video_url"
    assert video_part["video_url"]["url"].startswith("data:video/mp4;base64,")
    assert video_part["video_url"]["fps"] == 1.0


def test_openai_compatible_video_provider_rejects_oversized_file(tmp_path):
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"too-large")
    provider = OpenAICompatibleVisionProvider(api_key="key", model_name="video-model")

    with pytest.raises(Exception, match="超过直传模型上限"):
        asyncio.run(provider.analyze_video(video, "prompt", max_video_bytes=2))
