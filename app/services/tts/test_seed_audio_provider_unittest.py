import base64
import tempfile
import unittest
from pathlib import Path

from app.services.tts.seed_audio_provider import SeedAudioError, SeedAudioProvider


class _Response:
    def __init__(self, payload, status_code=200, content_type="application/json", content=b""):
        self._payload = payload
        self.status_code = status_code
        self.headers = {"content-type": content_type, "x-request-id": "req-1"}
        self.content = content

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("download failed")


class _Session:
    def __init__(self, responses, downloads=None):
        self.responses = list(responses)
        self.downloads = list(downloads or [])
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return self.downloads.pop(0)


class SeedAudioProviderTests(unittest.TestCase):
    def test_create_request_uses_api_key_and_48khz_audio_config(self):
        audio = b"fake-mp3"
        session = _Session([_Response({"data": {"audio": base64.b64encode(audio).decode()}})])
        provider = SeedAudioProvider(
            api_key="secret",
            speaker="speaker-a",
            session=session,
            max_retries=1,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "voice.mp3"
            result = provider.synthesize("你好", output, language="zh-CN", voice_prompt="沉稳", speed=1.2)
            self.assertEqual(audio, output.read_bytes())
            self.assertEqual("req-1", result.request_id)

        _, url, call = session.calls[0]
        self.assertEqual("https://openspeech.bytedance.com/api/v3/tts/create", url)
        self.assertEqual("secret", call["headers"]["X-Api-Key"])
        self.assertNotIn("secret", str(call["json"]))
        self.assertEqual("seed-audio-1.0", call["json"]["model"])
        self.assertEqual([{"speaker": "speaker-a"}], call["json"]["references"])
        self.assertEqual(48000, call["json"]["audio_config"]["sample_rate"])
        self.assertEqual(20, call["json"]["audio_config"]["speech_rate"])
        self.assertIn("沉稳", call["json"]["text_prompt"])
        self.assertIn("你好", call["json"]["text_prompt"])
        self.assertTrue(call["headers"]["X-Api-Request-Id"])

    def test_pure_text_request_does_not_require_speaker_or_references(self):
        audio = b"pure-text-mp3"
        session = _Session([_Response({"code": 0, "audio": base64.b64encode(audio).decode()})])
        provider = SeedAudioProvider(
            api_key="secret",
            speaker="",
            references=[],
            session=session,
            max_retries=1,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "voice.mp3"
            provider.synthesize("生成一段自然的中文旁白", output)

        payload = session.calls[0][2]["json"]
        self.assertNotIn("references", payload)
        self.assertEqual("生成一段自然的中文旁白", payload["text_prompt"])
        self.assertTrue(provider.configured)

    def test_request_voice_overrides_configured_speaker(self):
        session = _Session([_Response({"audio_base64": base64.b64encode(b"mp3").decode()})])
        provider = SeedAudioProvider(
            api_key="secret",
            speaker="default-speaker",
            session=session,
            max_retries=1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            provider.synthesize("hello", Path(temp_dir) / "voice.mp3", voice_id="request-speaker")
        payload = session.calls[0][2]["json"]
        self.assertEqual([{"speaker": "request-speaker"}], payload["references"])

    def test_downloads_audio_url_response(self):
        session = _Session(
            [_Response({"result": {"audio_url": "https://example.test/audio.mp3"}})],
            [_Response(None, content_type="audio/mpeg", content=b"downloaded")],
        )
        provider = SeedAudioProvider(
            api_key="secret",
            speaker="speaker",
            session=session,
            max_retries=1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "voice.mp3"
            provider.synthesize("hello", output)
            self.assertEqual(b"downloaded", output.read_bytes())

    def test_missing_key_and_upstream_errors_are_sanitized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(SeedAudioError) as caught:
                SeedAudioProvider(api_key="", speaker="speaker").synthesize(
                    "hello", Path(temp_dir) / "voice.mp3"
                )
        self.assertEqual("PROVIDER_NOT_CONFIGURED", caught.exception.code)

        provider = SeedAudioProvider(
            api_key="secret",
            speaker="speaker",
            session=_Session([_Response({"message": "bad"}, status_code=401)]),
            max_retries=1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(SeedAudioError) as caught:
                provider.synthesize("hello", Path(temp_dir) / "voice.mp3")
        self.assertNotIn("secret", str(caught.exception))

    def test_rejects_text_prompt_over_3000_characters(self):
        provider = SeedAudioProvider(api_key="secret", speaker="")
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(SeedAudioError, "3000"):
                provider.synthesize("字" * 3001, Path(temp_dir) / "voice.mp3")

    def test_surfaces_success_http_with_provider_error_code(self):
        provider = SeedAudioProvider(
            api_key="secret",
            session=_Session([_Response({"code": 45000010, "message": "Invalid X-Api-Key"})]),
            max_retries=1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(SeedAudioError, "Invalid X-Api-Key") as caught:
                provider.synthesize("hello", Path(temp_dir) / "voice.mp3")
        self.assertEqual(45000010, caught.exception.provider_code)


if __name__ == "__main__":
    unittest.main()
