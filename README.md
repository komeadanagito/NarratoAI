# NarratoAI 批量视频处理 API

NarratoAI 提供影视解说、脚本与字幕处理、语音合成、视频剪辑，以及本地批量视频处理 HTTP API。原 Streamlit 控制台已移除；当前后端默认仅监听本机 `127.0.0.1:8080`。

## 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- FFmpeg / FFprobe
- ImageMagick

## 安装与启动

```bash
uv sync
cp config.example.toml config.toml
uv run python -m app
```

服务启动后，API 根地址为 `http://127.0.0.1:8080/api/v1`。仅执行核心模块和 Provider 自检并输出 JSON：

```bash
uv run python -m app --check
```

开发时可覆盖监听地址、端口并启用热重载：

```bash
uv run python -m app --host 127.0.0.1 --port 8080 --reload
```

## API

接口契约见 [docs/backend_api.yaml](docs/backend_api.yaml)。首版提供五个操作：

- `GET /api/v1/health`：健康检查。
- `POST /api/v1/uploads/videos`：批量上传 MP4/MOV 视频。
- `POST /api/v1/batches`：创建异步批处理任务。
- `GET /api/v1/batches/{batch_id}`：轮询批次进度和结果。
- `GET /api/v1/artifacts/{artifact_id}/download`：下载已注册的成品视频。

最小调用顺序如下。把响应中的 ID 填入后续变量；`output_directory` 必须位于服务端配置的允许目录内。

```bash
BASE=http://127.0.0.1:8080/api/v1

curl "$BASE/health"
curl -X POST "$BASE/uploads/videos" -F "files=@./input.mp4"

UPLOAD_ID="替换为上传响应中的 uploads[0].id"
curl -X POST "$BASE/batches" \
  -H "Content-Type: application/json" \
  -d "{\"upload_ids\":[\"$UPLOAD_ID\"],\"output_directory\":\"./storage/outputs\",\"concurrency\":1,\"narration\":{\"enabled\":false}}"

BATCH_ID="替换为创建响应中的 batch.id"
curl "$BASE/batches/$BATCH_ID"

ARTIFACT_ID="替换为成功任务中的 batch.jobs[0].artifact_id"
curl -L "$BASE/artifacts/$ARTIFACT_ID/download" -o result.mp4
```

批次是进程内异步任务；前端可每 1 至 2 秒轮询一次。`concurrency` 必须是大于等于 1 的整数，接口不设置上限，请按机器资源合理填写。服务重启后，既有批次和产物 ID 不会恢复。

## 后端与 AI 配置

运行参数放在本地 `config.toml`；模型、端点和活动模型放在
`config/models.json`。默认已经选择 Ark 的
`doubao-seed-2-1-turbo-260628`，并同时用于视觉和文本：

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

```

模型密钥只通过 `config/models.json` 指定的环境变量提供：

```bash
export VOLCANO_ARK_API_KEY=your_ark_api_key
export SEED_AUDIO_API_KEY=your_seed_audio_api_key
```

Seed Audio 使用 `/api/v3/tts/create`、`X-Api-Key`、
`seed-audio-1.0` 和 48 kHz MP3。请在 `config/models.json` 的
`speaker` 中填写默认 speaker，也可以由批处理请求的 `voice_id` 覆盖。

新增或切换其他 LLM 时，在 `llm_profiles` 中增加 OpenAI-compatible
profile，再修改 `active.vision` / `active.text`；业务代码无需修改。

## 测试

```bash
uv run pytest -q
```

## Docker

```bash
docker build -t narratoai .
docker run --rm -p 8080:8080 narratoai
```

镜像创建 `storage/uploads` 和 `storage/outputs`，并在容器内监听 `0.0.0.0:8080`。实际使用时请挂载本地配置、上传和输出目录。

## Python 核心服务

HTTP API 之外仍可直接复用 `app.services.llm`、`app.services.documentary`、`app.services.voice`、`app.services.subtitle` 和 `app.services.task` 等 Python 模块。

## 许可证

参见 [LICENSE](LICENSE)。
