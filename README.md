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

复制 `config.example.toml` 后，在本地 `config.toml` 中调整运行参数：

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

生产凭据推荐通过环境变量提供：

```bash
export SEED_AUDIO_APP_ID=your_app_id
export SEED_AUDIO_ACCESS_TOKEN=your_access_token
```

Seed Audio V3 按官方 HTTP 协议使用 24 kHz；`voice_prompt` 中可识别的常见情绪会映射到音色的标准情绪参数，最终是否支持取决于所选音色。

开启 `narration.enabled=true` 还必须在 `[app]` 中配置可用的视觉和文本 OpenAI 兼容模型；火山 Ark 视觉接口可填写 `vision_openai_base_url`、`vision_openai_model_name` 和 `vision_openai_api_key`。API Key 只保存在服务端，不通过批处理接口传入，也不要提交 `config.toml`。

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
