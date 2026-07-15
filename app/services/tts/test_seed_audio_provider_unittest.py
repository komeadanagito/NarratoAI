import base64
import json
import tempfile
import unittest
from pathlib import Path

from app.services.tts.seed_audio_provider import SeedAudioError, SeedAudioProvider


class _Response:
    def __init__(self, payload, status_code=200, content_type="application/json"):
        self._payload = payload
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.content = b""

    def json(self):
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class SeedAudioProviderTests(unittest.TestCase):
    def test_synthesize_writes_audio_and_does_not_put_token_in_payload(self):
        audio = b"fake-mp3"
        session = _Session(
            [_Response({"code": 3000, "data": base64.b64encode(audio).decode(), "addition": {"duration": "1234"}})]
        )
        provider = SeedAudioProvider(
            app_id="app",
            access_token="secret",
            voice_type="voice",
            session=session,
            max_retries=1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "voice.mp3"
            result = provider.synthesize("你好", output, language="zh-TW")
            self.assertEqual(audio, output.read_bytes())
            self.assertEqual(1234, result.duration_ms)

        _, call = session.calls[0]
        self.assertEqual("Bearer;secret", call["headers"]["Authorization"])
        self.assertNotIn("secret", str(call["json"]))
        self.assertEqual("zh-cn", call["json"]["audio"]["explicit_language"])
        self.assertEqual(24000, call["json"]["audio"]["rate"])

    def test_voice_prompt_maps_only_to_documented_emotion_fields(self):
        session = _Session(
            [_Response({"code": 3000, "data": base64.b64encode(b"mp3").decode()})]
        )
        provider = SeedAudioProvider(
            app_id="app",
            access_token="secret",
            voice_type="voice",
            session=session,
            max_retries=1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            provider.synthesize(
                "你好",
                Path(temp_dir) / "voice.mp3",
                voice_prompt="成熟、克制、略带悬疑感",
            )

        audio = session.calls[0][1]["json"]["audio"]
        request = session.calls[0][1]["json"]["request"]
        self.assertTrue(audio["enable_emotion"])
        self.assertEqual("neutral", audio["emotion"])
        self.assertNotIn("extra_param", request)

    def test_chunked_success_and_malformed_json_are_defensive(self):
        audio = b"chunk-audio"

        class ChunkedResponse(_Response):
            def __init__(self):
                super().__init__(None)
                self.content = (
                    json.dumps({"code": 0, "data": base64.b64encode(audio).decode()})
                    + "\n"
                    + json.dumps({"code": 20000000, "message": "OK"})
                ).encode()

            def json(self):
                raise ValueError("stream")

        provider = SeedAudioProvider(
            app_id="app",
            access_token="secret",
            voice_type="voice",
            session=_Session([ChunkedResponse()]),
            max_retries=1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "voice.mp3"
            provider.synthesize("hello", output)
            self.assertEqual(audio, output.read_bytes())

        malformed = SeedAudioProvider(
            app_id="app",
            access_token="secret",
            voice_type="voice",
            session=_Session([_Response([])]),
            max_retries=1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(SeedAudioError):
                malformed.synthesize("hello", Path(temp_dir) / "bad.mp3")

    def test_rejects_text_over_provider_byte_limit(self):
        provider = SeedAudioProvider(
            app_id="app",
            access_token="secret",
            voice_type="voice",
            session=_Session([]),
            max_retries=1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(SeedAudioError) as caught:
                provider.synthesize("你" * 342, Path(temp_dir) / "voice.mp3")
        self.assertEqual(3010, caught.exception.provider_code)

    def test_provider_error_is_sanitized(self):
        session = _Session([_Response({"code": 3050, "message": "bad voice"})])
        provider = SeedAudioProvider(
            app_id="app",
            access_token="secret",
            voice_type="voice",
            session=session,
            max_retries=1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(SeedAudioError) as caught:
                provider.synthesize("hello", Path(temp_dir) / "voice.mp3")
        self.assertEqual(3050, caught.exception.provider_code)
        self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
