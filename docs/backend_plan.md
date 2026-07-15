# 批量视频处理与 AI 解说后端开发计划

> 需求来源：[`batch_deduplication_design.md`](./batch_deduplication_design.md)
> 接口契约：[`backend_api.yaml`](./backend_api.yaml)
> 对齐版本：OpenAPI `1.0.0`
> 文档状态：Ready for implementation
> 适用范围：仅处理用户拥有版权或已获授权的视频素材。

## 1. 目标与范围

本期按照 `backend_api.yaml` 实现一个本地单机后端，为单页面前端提供最小可用闭环：

1. `GET /health` 检查服务是否可用。
2. `POST /uploads/videos` 批量上传视频并返回上传 ID。
3. `POST /batches` 创建异步批处理任务。
4. `GET /batches/{batch_id}` 供前端每 1 至 2 秒轮询批次进度和结果。
5. `GET /artifacts/{artifact_id}/download` 下载处理成功的视频。
6. 每个视频可选择直接执行内容变换，或先生成 AI 解说、配音和字幕，再执行内容变换。

本计划以 API 文件为唯一公共契约。实现不得擅自增加必填字段、修改状态枚举或改变响应包裹结构。

### 1.1 本期不实现

- SSE、WebSocket 或其他主动进度推送。
- 批次取消、任务重试、批次列表、上传详情和上传删除接口。
- 用户体系、Bearer Token、计费和多租户隔离。
- SQLite、Redis、分布式队列和应用重启后的任务恢复。
- 前端页面、Streamlit 集成或服务端目录浏览器。
- 对任何分发平台审核结果或“去重成功率”的保证。

首期服务默认只监听 `127.0.0.1`。如果未来需要公网部署，必须另行设计鉴权、TLS、限流、持久化和租户隔离，并同步升级 API 契约。

## 2. API 实现边界

| 路由 | `operationId` | Handler | 核心服务 | 同步/异步 |
| --- | --- | --- | --- | --- |
| `GET /health` | `getHealth` | `health.py` | 本地运行状态检查 | 同步 |
| `POST /uploads/videos` | `uploadVideos` | `uploads.py` | `UploadService` | 同步流式落盘 |
| `POST /batches` | `createBatch` | `batches.py` | `BatchProcessor` | 异步，返回 `202` |
| `GET /batches/{batch_id}` | `getBatch` | `batches.py` | `BatchStore` | 同步查询快照 |
| `GET /artifacts/{artifact_id}/download` | `downloadArtifact` | `artifacts.py` | `ArtifactService` | 流式响应 |

公共响应必须严格匹配 API：

- 健康检查：`{"status": "ok"}`。
- 上传成功：`{"uploads": [...]}`。
- 创建和查询批次：`{"batch": {...}}`。
- 请求失败：`{"code": "稳定错误码", "message": "错误说明"}`。
- 下载成功：文件流，不返回 JSON 包裹。

服务端异常堆栈、真实供应商响应、API Key 和不受控绝对路径不得出现在响应中。

## 3. 当前代码复用与开发差距

| 能力 | 当前状态 | 实现决策 |
| --- | --- | --- |
| FFmpeg / MoviePy 合成 | 已有 `generate_video.merge_materials()` | 复用；新增内容变换服务，FFmpeg 优先 |
| 字幕遮罩和烧录 | 已有 | 复用遮罩参数和合成路径 |
| 视频裁剪、TTS、字幕合成 | 已有 `task.start_subclip_unified()` | 复用核心步骤，增加批处理适配器 |
| 视频抽帧和视觉分析 | 已有 `DocumentaryFrameAnalysisService` | 配置火山 Ark OpenAI 兼容接口后复用 |
| 豆包 TTS | 只有旧版 `/api/v1/tts` | 新增 Seed Audio v3 Provider，不改旧适配器行为 |
| 上传校验 | 只有本地路径校验 | 新增 multipart 流式上传、大小和媒体校验 |
| 任务状态 | 只有简单 `MemoryState` | 新增线程安全的 `BatchStore`，仅在进程内保存 |
| 批量调度 | 缺失 | 新增有界 `ThreadPoolExecutor` |
| 内容变换滤镜 | 大部分缺失 | 新增 FFmpeg 滤镜计划和执行服务 |
| HTTP 服务 | 缺失 | 新增 FastAPI + Uvicorn 应用 |

`task.py` 目前使用模块级 `merged_audio_path` 和 `merged_subtitle_path`。在开放并发前必须将它们改为函数局部变量或单任务上下文，否则不同视频任务可能互相覆盖产物路径。

## 4. 模块设计

```text
app/
├── api/
│   ├── main.py                     # FastAPI 应用、生命周期、异常映射
│   └── routes/
│       ├── health.py               # GET /health
│       ├── uploads.py              # POST /uploads/videos
│       ├── batches.py              # POST/GET /batches
│       └── artifacts.py            # GET /artifacts/{id}/download
├── models/
│   └── batch_schema.py             # 与 OpenAPI 对齐的 Pydantic 模型
└── services/
    ├── upload_service.py           # 流式落盘、校验、Upload ID 映射
    ├── batch_processor.py          # 批次创建、线程池调度、状态聚合
    ├── batch_store.py              # 线程安全的内存状态快照
    ├── deduplication_service.py    # FFmpeg 内容变换
    ├── narration_pipeline.py       # 视觉、文案、TTS、字幕、合成
    ├── artifact_service.py         # Artifact ID、路径校验、下载
    └── tts/
        └── seed_audio_provider.py  # Seed Audio v3 适配器
```

需要新增的运行依赖：

```toml
fastapi = "..."
uvicorn = { version = "...", extras = ["standard"] }
python-multipart = "..."
```

实现时通过 `uv add` 选择兼容 Python 3.12 的稳定版本并更新锁文件，不在计划中预设未验证的版本号。

## 5. 数据模型与状态机

### 5.1 Upload

API 只返回：

- `id`：UUID。
- `file_name`：净化后的展示名称。
- `size_bytes`：实际落盘字节数。

内部还需保存 `stored_path`、扩展名和媒体探测结果，但不得通过公共响应返回。

### 5.2 Batch

`POST /batches` 的 `BatchCreateRequest` 顶层字段：

| 字段 | 必填 | 后端处理 |
| --- | --- | --- |
| `upload_ids` | 是 | 去重并解析为已注册的上传文件，任一 ID 不存在则返回 `404` |
| `output_directory` | 是 | 按第 6.2 节执行白名单和可写性校验 |
| `concurrency` | 否 | 默认 1，API 范围 `1..16`，再受服务端实际上限约束 |
| `narration` | 否 | 缺省等价于 `enabled=false` |
| `deduplication` | 否 | 缺省时使用 OpenAPI 中各字段的默认值 |

公共字段严格为：

- `id`。
- `status`：`queued | processing | succeeded | partially_succeeded | failed`。
- `progress`：`0..100`。
- `total`、`succeeded`、`failed`。
- `jobs`。

状态转换：

```text
queued -> processing -> succeeded
                     -> partially_succeeded
                     -> failed
```

聚合规则：

- 全部 Job 成功：`succeeded`。
- 部分成功、部分失败：`partially_succeeded`。
- 全部失败：`failed`。
- 仍有 queued/processing Job：批次保持 `processing`。
- 批次进度为所有 Job 进度的算术平均值，取整并保证不倒退。

### 5.3 VideoJob

公共状态：`queued | processing | succeeded | failed`。

公共阶段：`queued | analyzing | synthesizing | processing | completed`。

每个 Job 必须返回 `id`、`upload_id`、`file_name`、`status`、`stage` 和 `progress`；`message`、`output_path`、`artifact_id`、`error` 根据执行状态选填。

阶段转换：

```text
不启用 AI：queued -> processing -> completed
启用 AI：  queued -> analyzing -> synthesizing -> processing -> completed
```

Job 成功后设置：

- `message = "处理成功了"`。
- `output_path`：最终保存路径。
- `artifact_id`：用于下载的 UUID。

Job 失败后设置 `error`，其结构严格为 `code + message`，不得继续进入 `completed`。

### 5.4 进度分配

不启用 AI：

| 阶段 | 进度范围 |
| --- | --- |
| 排队与媒体检查 | `0–10` |
| 内容变换和转码 | `10–95` |
| 输出验收与注册 | `95–100` |

启用 AI：

| 阶段 | 进度范围 |
| --- | --- |
| 媒体检查与抽帧分析 | `0–35` |
| 文案与 TTS 合成 | `35–60` |
| 字幕、音视频合成和内容变换 | `60–95` |
| 输出验收与注册 | `95–100` |

## 6. 文件与路径策略

### 6.1 上传目录

```text
storage/
├── uploads/{upload_id}/source.{ext}
└── tasks/{batch_id}/{job_id}/
│   ├── analysis.json
│   ├── script.json
│   ├── narration.mp3
│   ├── subtitle.srt
│   └── intermediate.mp4

{allowed_output_root}/{output_directory}/
└── {safe_source_name}_{short_id}.mp4
```

上传规则：

1. 使用分块读取，不能把整个视频一次性读入内存。
2. 文件名只用于展示，实际路径使用 UUID。
3. 同时检查扩展名、文件签名和 `ffprobe` 解码结果。
4. 支持格式由服务端配置，初始为 `.mp4`、`.mov`，需要时可增加 `.mkv`、`.webm`。
5. 超过单文件大小上限时立即停止写入、删除临时文件并返回 `413`。
6. 先写入 `.part`，验证成功后使用原子重命名完成落盘。

### 6.2 `output_directory` 校验

API 要求前端传入 `output_directory`，但服务端不能接受任意文件系统路径：

1. 将输入路径展开并解析为规范绝对路径。
2. 目标必须位于 `allowed_output_roots` 配置的白名单目录内。
3. 拒绝 `..` 穿越、空路径、目标为普通文件、不可写目录和越界符号链接。
4. 允许在白名单范围内创建不存在的子目录。
5. 每个输出文件采用净化后的原文件名加唯一短 ID，防止覆盖。
6. `output_path` 按 API 契约返回实际成品路径；下载接口仍只通过 `artifact_id` 解析文件。

### 6.3 产物下载

`ArtifactService` 在内存中保存 `artifact_id -> output_path` 映射，文件本身只保留在已校验的导出目录。下载时必须重新验证目标是已注册的普通文件，不能把 URL 参数直接拼接成路径。

响应优先使用 `video/mp4`；其他受支持产物使用 `application/octet-stream`。使用流式文件响应，避免大文件进入 Python 内存。

## 7. 批量调度

- `POST /batches` 只完成参数校验、Upload ID 解析、状态初始化和任务入队，然后立即返回 `202`。
- 使用一个应用级有界 `ThreadPoolExecutor`。
- 请求中的 `concurrency` 范围为 `1..16`，实际批次并发为：

```text
min(请求 concurrency, 服务端 max_batch_workers, 当前可用工作槽)
```

- 视频任务并发数与单个 FFmpeg 的 `-threads` 分开配置，避免 CPU 过度订阅。
- 线程池队列达到上限时返回 `429`，不创建半初始化批次。
- 一个 Job 失败不能中断同批其他 Job。
- `BatchStore` 使用 `threading.RLock`，对外返回深拷贝或不可变快照，防止轮询线程读到修改中的字典。
- 状态只保存在内存中；应用重启后旧 `batch_id` 返回 `404`。这是 MVP 的明确限制。

## 8. 内容变换实现

`DeduplicationOptions` 必须与 API 完全一致：

| API 字段 | 处理行为 |
| --- | --- |
| `change_file_hash` | 在最终编码/封装时写入唯一安全元数据，确保输出二进制摘要变化 |
| `reencode` | 使用服务端统一编码参数重新编码视频；启用滤镜时强制重新编码 |
| `color_noise_tweak` | 在服务端安全范围内随机组合 `eq` 和轻量 `noise` |
| `border_mode=none` | 不增加边框 |
| `border_mode=solid` | 使用 `pad` 增加轻量纯色边框 |
| `border_mode=blurred` | 使用背景缩放、模糊和前景叠加形成边框 |
| `sticker` | 从 `resource/stickers` 白名单中选择 PNG 并叠加 |
| `subtitle_mask` | 在原硬字幕区域应用现有柔化遮罩 |
| `crop_scale` | 在安全范围内随机轻微裁剪或缩放后恢复目标尺寸 |
| `mirror` | 为 true 时启用随机水平镜像决策，为 false 时绝不镜像 |
| `speed_tweak` | 在 `0.99x..1.01x` 内随机同步调整视频 PTS 和音频 tempo |

内部可以生成随机种子和实际滤镜参数用于日志排查，但 API v1 不返回这些字段。

实现接口：

```python
def apply_direct_deduplication(
    input_path: str,
    output_path: str,
    options: DeduplicationOptions,
    *,
    progress_callback: Callable[[int, str], None] | None = None,
) -> str:
    """处理单个视频，成功返回输出路径，失败抛出领域异常。"""
```

FFmpeg 命令必须使用参数数组并通过 `subprocess` 直接执行，禁止将用户输入拼成 shell 命令字符串。

## 9. AI 解说流水线

当 `narration.enabled=false` 时，不允许调用视觉模型、文本模型或 TTS，直接保留原声并进入内容变换。

当 `narration.enabled=true` 时：

1. 使用 `DocumentaryFrameAnalysisService` 抽帧并分析视频内容。
2. 通过服务端配置的文本模型生成解说脚本。
3. 根据 `language`、可选 `voice_id` 和 `voice_prompt` 调用 Seed Audio。
4. 生成解说音频和字幕时间轴。
5. 复用现有剪辑、音频、字幕合成能力生成解说版视频。
6. 对解说版视频执行第 8 节的内容变换。
7. 使用 `ffprobe` 验收最终文件并注册 Artifact。

默认供应商配置：

| 配置项 | 默认/示例值 |
| --- | --- |
| `vision_openai_base_url` | `https://ark.cn-beijing.volces.com/api/v3` |
| `vision_openai_model_name` | `doubao-seed-2-1-turbo-260628` |
| `vision_openai_api_key` | 环境变量 `VOLCANO_ARK_API_KEY` |
| `seed_audio_api_url` | `https://openspeech.bytedance.com/api/v3/tts/create` |
| `seed_audio_model` | `seed-audio-1.0` |
| `seed_audio_api_key` | 环境变量 `SEED_AUDIO_API_KEY` |

真实密钥不得进入 Git、日志、批次状态或错误响应。当前旧版 `doubaotts_tts()` 使用 `/api/v1/tts`，不能当作 Seed Audio v3 已完成；必须通过独立 Provider 适配并使用 mock 测试请求格式。

## 10. 错误码与 HTTP 映射

| 场景 | HTTP | `code` |
| --- | --- | --- |
| 请求字段或组合无效 | `400` | `INVALID_REQUEST` |
| 文件超过上限 | `413` | `FILE_TOO_LARGE` |
| 上传格式或媒体无效 | `400` | `UNSUPPORTED_MEDIA` |
| Upload ID 不存在 | `404` | `UPLOAD_NOT_FOUND` |
| Batch ID 不存在 | `404` | `BATCH_NOT_FOUND` |
| Artifact ID 不存在 | `404` | `ARTIFACT_NOT_FOUND` |
| 输出目录越界或不可写 | `400` | `OUTPUT_PATH_NOT_ALLOWED` |
| 工作队列已满 | `429` | `QUEUE_FULL` |
| AI/TTS 未配置 | `400` | `PROVIDER_NOT_CONFIGURED` |
| 上游 AI/TTS 调用失败 | Job 失败 | `UPSTREAM_FAILED` |
| FFmpeg 或媒体处理失败 | Job 失败 | `PROCESSING_FAILED` |
| 未预期服务端错误 | `500` | `INTERNAL_ERROR` |

异步处理开始后的错误写入对应 `VideoJob.error`，由轮询接口返回；不能把整个批次 HTTP 查询变成 `500`。

## 11. 开发阶段

### 阶段 1：API 骨架和模型

- 添加 FastAPI、Uvicorn、multipart 依赖。
- 建立 `app/api/main.py` 和四个路由模块。
- 将 OpenAPI schema 转为 Pydantic 请求/响应模型。
- 实现统一领域异常到 `{code, message}` 的映射。
- 增加启动命令和 `/health` 测试。

交付标准：服务能启动，五个 operationId 都有对应路由，OpenAPI 响应模型与 YAML 一致。

### 阶段 2：上传、路径和产物

- 实现分块上传、临时文件、大小限制、格式和 ffprobe 校验。
- 实现 Upload ID 注册。
- 实现 `output_directory` 白名单校验。
- 实现 Artifact 注册和流式下载。

交付标准：上传和下载闭环通过；路径穿越、越界符号链接和超限文件被拒绝。

### 阶段 3：单视频内容变换

- 实现 FFmpeg 滤镜计划构建器。
- 完成 API 中全部内容变换开关。
- 实现 FFmpeg 进度解析、超时和输出验收。
- 验证有声、无声、横屏、竖屏和不同容器输入。

交付标准：每个开关可独立及组合运行，输出可被 ffprobe 和播放器完整读取。

### 阶段 4：AI 解说

- 接入 Ark 视觉分析配置。
- 新增 Seed Audio v3 Provider。
- 隔离 `task.py` 的模块级任务变量。
- 串联分析、文案、TTS、字幕、合成和最终内容变换。

交付标准：关闭 AI 时零模型请求；开启 AI 时输出带解说和字幕的有效视频。

### 阶段 5：批量调度和轮询

- 实现线程安全 BatchStore。
- 实现有界 BatchProcessor 和状态聚合。
- 接通创建批次与查询批次路由。
- 验证并发上限、部分成功和队列满行为。

交付标准：多个视频能按 `concurrency` 运行，前端只通过轮询即可准确展示每个 Job 的状态和产物。

### 阶段 6：质量和交付

- 完成单元、API、媒体和外部 Provider mock 测试。
- 进行 1、2、4 个并发任务的 CPU、内存、磁盘基准测试。
- 更新 `config.example.toml`、README 和启动命令。
- 执行密钥、临时文件、日志和错误响应检查。

交付标准：测试全绿，样例批次完整跑通，API 契约检查无漂移。

## 12. 测试计划

### 12.1 API 契约测试

- 五个路由的成功状态码和响应结构。
- `BatchCreateRequest` 必填字段、并发边界和未知字段拒绝。
- 所有枚举值与 YAML 一致。
- 错误响应只包含 `code`、`message`。
- 使用 OpenAPI 文件做 schema 回归检查，防止实现与文档漂移。

### 12.2 上传与安全测试

- 多文件上传、同名文件、空文件、伪造扩展名和损坏视频。
- 单文件超限时停止读取并清理 `.part` 文件。
- `output_directory` 的绝对路径、相对路径、`..`、符号链接和不可写目录。
- Artifact ID 无法下载未注册文件或目录外文件。
- FFmpeg 参数不经过 shell 拼接。

### 12.3 媒体测试

- 所有内容变换开关的单独和常用组合。
- MP4/MOV、有声/无声、横屏/竖屏、固定/可变帧率。
- 变速后音视频时长误差不超过 100ms 或总时长的 0.5%。
- 输入文件不被修改，启用 `change_file_hash` 后输出摘要不同。
- 最终输出可通过 `ffprobe` 和完整解码检查。

### 12.4 批量与 Provider 测试

- concurrency 为 1、边界 16 和超过服务端上限时的行为。
- 一个 Job 失败时其他 Job 继续运行，批次进入 `partially_succeeded`。
- 轮询过程中 progress 单调递增，终态固定为 100。
- AI 关闭时断言 Provider 零调用。
- Ark/Seed Audio 的成功、超时、限流、错误响应和敏感信息脱敏。

## 13. 验收标准

1. API 中 5 个操作全部实现，状态码和响应结构与 YAML 一致。
2. 前端能完成“上传 → 创建批次 → 轮询 → 展示路径/下载”的完整流程。
3. `narration.enabled=false` 时保留原声并完成内容变换。
4. `narration.enabled=true` 时生成解说、配音、字幕和最终视频。
5. 所有 DeduplicationOptions 均有效，组合使用不会生成不可播放文件。
6. 多视频任务按有效并发上限执行，单个失败不影响其他任务。
7. `output_directory` 不能越过服务端允许根目录，下载接口不能读取未注册文件。
8. API Key 不出现在 Git、日志、状态或响应中。
9. 工作区测试通过，并提供本地启动和最小 curl 调用说明。

## 14. 已知限制与待确认事项

| 项目 | 当前决定/待确认点 |
| --- | --- |
| 任务持久化 | v1 仅内存；服务重启后批次状态丢失 |
| 上传保留期 | 待确定自动清理时间；首版提供配置项 |
| 输出目录 | 必须确认默认 `allowed_output_roots` |
| 单文件上限 | 待产品确定；由服务端配置，API 不写死 |
| 最大批次文件数 | 待产品确定；必须有服务端上限 |
| 最大并发 | API 允许到 16，服务器可设置更小的实际上限 |
| Seed Audio 时间戳 | 需确认是否返回字/句级时间戳；否则采用分段时长或 ASR 回标 |
| Seed Audio 音色 | 需确认预置音色与声音克隆的授权、保存和删除规则 |
| 任务取消/重试 | 不在 v1 API 范围，后续版本新增接口后再实现 |
| 公网部署 | 不在 v1 范围；届时必须补鉴权和持久化 |
