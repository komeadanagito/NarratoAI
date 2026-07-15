# NarratoAI Batch Video API

NarratoAI provides film narration, script and subtitle processing, speech synthesis, video editing, and a local batch-processing HTTP API. The former Streamlit console has been removed; the backend listens on `127.0.0.1:8080` by default.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- FFmpeg / FFprobe
- ImageMagick

## Install and Run

```bash
uv sync
cp config.example.toml config.toml
uv run python -m app
```

The API base URL is `http://127.0.0.1:8080/api/v1`. To check the core modules and provider registration, print JSON, and exit without starting the server, run:

```bash
uv run python -m app --check
```

For development, the listen address and port can be overridden and reload enabled:

```bash
uv run python -m app --host 127.0.0.1 --port 8080 --reload
```

## API

See [docs/backend_api.yaml](docs/backend_api.yaml) for the contract. Version 1 exposes five operations:

- `GET /api/v1/health`: health check.
- `POST /api/v1/uploads/videos`: upload one or more MP4/MOV videos.
- `POST /api/v1/batches`: create an asynchronous processing batch.
- `GET /api/v1/batches/{batch_id}`: poll batch progress and results.
- `GET /api/v1/artifacts/{artifact_id}/download`: download a registered output video.

The minimal call sequence is shown below. Copy the returned IDs into the following variables. `output_directory` must be inside a server-configured allowed root.

```bash
BASE=http://127.0.0.1:8080/api/v1

curl "$BASE/health"
curl -X POST "$BASE/uploads/videos" -F "files=@./input.mp4"

UPLOAD_ID="REPLACE_WITH_UPLOAD_ID"
curl -X POST "$BASE/batches" \
  -H "Content-Type: application/json" \
  -d "{\"upload_ids\":[\"$UPLOAD_ID\"],\"output_directory\":\"./storage/outputs\",\"concurrency\":1,\"narration\":{\"enabled\":false}}"

BATCH_ID="REPLACE_WITH_BATCH_ID"
curl "$BASE/batches/$BATCH_ID"

ARTIFACT_ID="REPLACE_WITH_ARTIFACT_ID"
curl -L "$BASE/artifacts/$ARTIFACT_ID/download" -o result.mp4
```

Batches are asynchronous and in-memory; clients may poll every one or two seconds. `concurrency` must be an integer greater than or equal to 1. The API does not impose an upper bound, so choose it according to the machine's resources. Existing batch and artifact IDs are not restored after a server restart.

## Backend and AI Configuration

After copying `config.example.toml`, adjust the local `config.toml`:

```toml
[backend]
host = "127.0.0.1"
port = 8080
upload_directory = "./storage/uploads"
allowed_output_roots = ["./storage/outputs"]
allowed_video_extensions = [".mp4", ".mov"]
max_upload_size_bytes = 2147483648
queue_capacity = 32
ffmpeg_threads = 2
ffmpeg_timeout_seconds = 3600

[seed_audio]
api_url = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
app_id = ""
access_token = ""
voice_type = ""
model = "seed-tts-1.1"
```

Prefer environment variables for production credentials:

```bash
export SEED_AUDIO_APP_ID=your_app_id
export SEED_AUDIO_ACCESS_TOKEN=your_access_token
```

Seed Audio V3 follows the official 24 kHz HTTP contract. Recognized common emotions in `voice_prompt` are mapped to standard emotion parameters; actual support depends on the selected voice.

Using `narration.enabled=true` also requires working OpenAI-compatible vision and text models in `[app]`. For Volcano Ark vision, set `vision_openai_base_url`, `vision_openai_model_name`, and `vision_openai_api_key`. Provider keys stay on the server, are never sent through the batch API, and must not be committed in `config.toml`.

## Tests

```bash
uv run pytest -q
```

## Docker

```bash
docker build -t narratoai .
docker run --rm -p 8080:8080 narratoai
```

The image creates `storage/uploads` and `storage/outputs` and listens on `0.0.0.0:8080` inside the container. Mount your local configuration, upload directory, and output directory for real workloads.

## Python Core Services

The Python modules under `app.services.llm`, `app.services.documentary`, `app.services.voice`, `app.services.subtitle`, and `app.services.task` remain directly reusable outside the HTTP API.

## License

See [LICENSE](LICENSE).
