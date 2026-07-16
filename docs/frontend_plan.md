# 极速批量去重与 AI 解说前端开发计划

> 需求来源：[`batch_deduplication_design.md`](./batch_deduplication_design.md)  
> API 契约：[`backend_api.yaml`](./backend_api.yaml)  
> 适用角色：前端开发  
> 文档状态：Draft 1.0

## 1. 建设目标

为 NarratoAI 新增一个独立 Web 前端，完成“选择多个视频 → 配置处理参数 → 一键上传并创建批次 → 查看逐视频进度 → 获取结果”的单页面闭环。

首期目标：

1. 支持拖拽或选择多个 `.mp4`、`.mov` 视频。
2. 展示已选择的视频数量、文件列表和上传状态。
3. 配置导出目录、并发数、AI 解说和全部去重开关。
4. 一键上传文件并创建批处理任务，防止重复提交。
5. 轮询批次状态，展示总进度和每个视频的处理状态。
6. 成功后展示输出路径，并允许播放或下载成片。
7. 对文件、表单、网络和后端处理错误提供明确反馈。

## 2. 本期范围

### 2.1 包含

- 一个“极速批量去重与 AI 解说”页面。
- 视频选择、校验、移除和重新选择。
- 批量上传及上传进度。
- 处理配置表单。
- 批次创建和状态轮询。
- 批次总进度、逐视频状态、失败原因和结果入口。
- 页面刷新后的运行中批次恢复。
- 基础响应式、无障碍和中英文文案结构。

### 2.2 不包含

- 登录、注册、权限、计费和多租户。
- 历史批次列表。
- 取消批次和失败任务重试，当前 API 未提供对应接口。
- 浏览器内配置 Ark、Seed Audio API Key；密钥只存在服务端。
- 高级滤镜数值调节；用户只操作开关，具体安全范围由服务端决定。
- 浏览器直接执行 FFmpeg 或保存到任意客户端目录。
- 对任何平台审核或“去重成功率”作结果承诺。

## 3. 前置事实与关键约束

### 3.1 当前仓库状态

- 当前仓库只有 Python Core，没有前端工程。
- 原 Streamlit WebUI 已移除，本期新建独立前端。
- 后端通过 `http://127.0.0.1:8080/api/v1` 提供 REST API。
- 当前进度方案是轮询，不依赖 SSE 或 WebSocket。

### 3.2 导出目录限制

普通浏览器无法通过目录选择器获得一个可直接交给服务端写入的真实系统路径。首期采用文本输入：

- 本地部署时，用户输入后端所在机器可访问的目录，例如 `./storage/outputs`。
- 前端显示提示：“该路径由后端服务读取，不是浏览器下载目录。”
- 不使用伪装成目录选择器的文件输入控件。
- 如果未来前后端不在同一台机器，应由后端改为预设目录或输出目录 ID，前端不再提交路径。

### 3.3 文件生命周期

当前 API 没有删除上传文件接口。前端因此采用“点击开始后再上传”的策略：

1. 选择阶段只在浏览器内保存 `File` 对象，不立即上传。
2. 用户可以自由增删和调整配置。
3. 点击“开始批量处理”后锁定本次文件与配置，开始上传。
4. 上传成功后立即创建批次。

后端仍需为“上传成功但创建批次失败”的临时文件提供 TTL 清理机制。

## 4. 技术方案

### 4.1 技术选型

| 范围 | 方案 | 原因 |
| --- | --- | --- |
| 框架 | React + TypeScript | 组件化、类型安全，适合状态较多的单页面工具 |
| 构建 | Vite | 独立前端启动和构建简单 |
| 服务端状态 | TanStack Query | 管理创建批次、状态缓存、定时轮询和重新聚焦刷新 |
| 表单状态 | React `useReducer` | 页面只有一份配置，不引入额外全局状态库 |
| 上传 | 原生 `XMLHttpRequest` | 可获得上传进度并支持中止，不额外引入请求库 |
| API 类型 | OpenAPI 生成类型 | 以 `backend_api.yaml` 为单一契约，减少手写类型漂移 |
| 样式 | CSS Modules + CSS Variables | 依赖少，便于主题和响应式维护 |
| 单元测试 | Vitest + React Testing Library | 覆盖状态、组件和交互 |
| API Mock | MSW | 用真实 HTTP 语义模拟上传、轮询和异常 |
| E2E | Playwright | 验证完整用户流程 |

不在计划中锁死依赖版本；初始化时安装当时稳定版本并提交 lockfile。

### 4.2 工程位置

在仓库根目录新增 `frontend/`，不把 Node 依赖混入 Python Core：

```text
frontend/
├── src/
│   ├── api/
│   │   ├── client.ts                 # JSON 请求、错误标准化
│   │   ├── uploads.ts                # XHR 文件上传
│   │   ├── batches.ts                # 创建和查询批次
│   │   ├── artifacts.ts              # 结果 URL
│   │   └── generated.ts              # OpenAPI 自动生成类型，禁止手改
│   ├── components/
│   │   ├── ConfigPanel/
│   │   ├── VideoDropzone/
│   │   ├── VideoList/
│   │   ├── BatchProgress/
│   │   ├── ResultActions/
│   │   └── Feedback/
│   ├── features/batch-deduplication/
│   │   ├── BatchDeduplicationPage.tsx
│   │   ├── configReducer.ts
│   │   ├── fileQueueReducer.ts
│   │   ├── useBatchWorkflow.ts
│   │   ├── useBatchPolling.ts
│   │   ├── validation.ts
│   │   └── types.ts
│   ├── hooks/
│   ├── i18n/
│   │   ├── zh-CN.ts
│   │   └── en.ts
│   ├── styles/
│   │   ├── tokens.css
│   │   └── globals.css
│   ├── test/
│   │   ├── mocks/
│   │   └── setup.ts
│   ├── App.tsx
│   └── main.tsx
├── e2e/
├── .env.example
├── package.json
├── tsconfig.json
└── vite.config.ts
```

### 4.3 环境变量

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8080/api/v1
```

- 只允许公开的前端配置进入 `VITE_*`。
- 不在前端环境变量、代码、Local Storage 或构建产物中保存供应商 API Key。
- 开发环境由 Vite Proxy 转发 `/api`，减少本地 CORS 配置成本。

## 5. 页面与组件设计

### 5.1 页面布局

桌面端采用左右两栏，移动端改为单列：

```text
┌─────────────────────────────────────────────────────────┐
│ 极速批量去重与 AI 解说                                  │
│ 仅处理拥有版权或已获授权的素材                          │
├──────────────────────┬──────────────────────────────────┤
│ 配置区               │ 文件与执行区                     │
│                      │                                  │
│ 导出目录             │ 拖拽 / 选择多个视频             │
│ 并发线程数           │ 当前已选择 N 个视频             │
│ AI 解说开关          │                                  │
│ 解说语言/语气        │ 文件名 | 大小 | 状态 | 进度      │
│ 去重开关组           │                                  │
│                      │ 批次总进度                       │
│                      │ [开始批量处理]                   │
└──────────────────────┴──────────────────────────────────┘
```

### 5.2 组件职责

#### `ConfigPanel`

- `OutputSettings`：导出目录、并发数。
- `NarrationSettings`：AI 解说开关；开启后显示语言、音色和语气描述。
- `DeduplicationSettings`：所有去重选项。
- 配置在上传开始后只读，任务结束后允许“使用相同配置处理新文件”。

#### `VideoDropzone`

- 支持拖入和文件选择，设置 `multiple`。
- `accept` 只用于改善选择体验，不能替代校验。
- 键盘可聚焦，可通过 Enter/Space 打开选择器。
- 上传或处理期间禁用继续添加文件。

#### `VideoList`

展示：

- 文件名。
- 文件大小。
- 当前状态。
- 上传或处理进度。
- 错误原因。
- 成功后的输出路径、播放和下载入口。

选择阶段允许删除；上传开始后不允许改变本次队列。

#### `BatchProgress`

- 显示批次百分比和 `成功数 / 总数 / 失败数`。
- 状态文案统一映射，不直接把后端英文枚举展示给用户。
- 部分成功时使用警告样式，不误显示为全量成功。

#### `ResultActions`

- `artifact_id` 存在时显示播放和下载按钮。
- `output_path` 存在时显示路径和复制按钮。
- 播放失败不影响下载入口。

## 6. 表单模型

前端配置与 API 字段一一对应：

```ts
interface BatchFormValues {
  outputDirectory: string
  concurrency: number
  narration: {
    enabled: boolean
    language: 'zh-CN' | 'zh-TW'
    voiceId?: string
    voicePrompt?: string
  }
  deduplication: {
    changeFileHash: boolean
    reencode: boolean
    colorNoiseTweak: boolean
    borderMode: 'none' | 'blurred' | 'solid'
    sticker: boolean
    subtitleMask: boolean
    cropScale: boolean
    mirror: boolean
    speedTweak: boolean
  }
}
```

提交前由映射函数统一转换为 API 的 `snake_case`，UI 组件内不散落字段转换逻辑。

默认值：

```ts
const defaultValues: BatchFormValues = {
  outputDirectory: './storage/outputs',
  concurrency: 1,
  narration: {
    enabled: false,
    language: 'zh-CN',
  },
  deduplication: {
    changeFileHash: true,
    reencode: true,
    colorNoiseTweak: false,
    borderMode: 'none',
    sticker: false,
    subtitleMask: false,
    cropScale: false,
    mirror: false,
    speedTweak: false,
  },
}
```

## 7. 前端状态设计

### 7.1 工作流状态

```text
idle
  → ready
  → uploading
  → creating_batch
  → processing
  → succeeded | partially_succeeded | failed
```

状态转换规则：

| 状态 | 可编辑配置 | 可增删文件 | 主按钮行为 |
| --- | --- | --- | --- |
| `idle` | 是 | 是 | 禁用 |
| `ready` | 是 | 是 | 开始处理 |
| `uploading` | 否 | 否 | 显示上传中 |
| `creating_batch` | 否 | 否 | 显示创建任务中 |
| `processing` | 否 | 否 | 显示处理中 |
| 终态 | 是 | 可清空后重选 | 处理新文件 |

### 7.2 文件项状态

```ts
type FileStatus =
  | 'selected'
  | 'uploading'
  | 'uploaded'
  | 'queued'
  | 'processing'
  | 'succeeded'
  | 'failed'
```

文件本地 ID 使用 `crypto.randomUUID()`，不要用文件名作为 React Key。文件名允许重复，但同一轮选择中对“名称 + 大小 + lastModified”完全相同的文件进行去重提示。

### 7.3 状态归属

- TanStack Query：批次服务端状态。
- `configReducer`：配置表单状态。
- `fileQueueReducer`：`File`、上传进度、`upload_id` 和本地错误。
- `sessionStorage`：仅保存当前 `batch_id`，用于页面刷新后恢复轮询。
- 不持久化 `File` 对象；上传前刷新页面需要重新选择文件。

## 8. API 对接方案

### 8.1 接口映射

| 用户动作 | API | 前端行为 |
| --- | --- | --- |
| 页面启动探活 | `GET /health` | 失败时显示“后端服务不可用” |
| 点击开始 | `POST /uploads/videos` | 上传视频并取得 `upload_ids` |
| 上传完成 | `POST /batches` | 提交配置，保存 `batch_id` |
| 查看进度 | `GET /batches/{batch_id}` | 活跃状态每 1.5 秒轮询 |
| 下载结果 | `GET /artifacts/{artifact_id}/download` | 新窗口播放或触发下载 |

### 8.2 上传策略

API 支持一次上传多个文件。前端首期采用一个 multipart 请求：

- 所有文件按选择顺序追加到 `files` 字段。
- XHR 展示整个上传请求的总进度。
- 文件行在上传阶段共享总进度，文案标记为“批量上传中”。
- XHR 超时、断网或用户离开页面时中止请求。
- 收到上传结果后，按响应顺序绑定 `upload_id`；若后端不能保证顺序，需要后端返回客户端关联 ID。

后续如果需要逐文件精确进度和单文件上传重试，可改成有限并发的单文件请求，不改变后端接口。

### 8.3 创建批次

提交前生成一次不可变请求快照：

```ts
const request = {
  upload_ids: uploadedFiles.map((file) => file.uploadId),
  output_directory: values.outputDirectory.trim(),
  concurrency: values.concurrency,
  narration: {
    enabled: values.narration.enabled,
    ...(values.narration.enabled && {
      language: values.narration.language,
      voice_id: values.narration.voiceId || undefined,
      voice_prompt: values.narration.voicePrompt?.trim() || undefined,
    }),
  },
  deduplication: mapDeduplicationOptions(values.deduplication),
}
```

- 主按钮触发后立即禁用，阻止双击。
- `POST /batches` 不进行自动重试，避免创建重复批次。
- 若请求超时且无法确认是否创建成功，提示用户检查后端日志；API 后续应增加幂等键以彻底解决该问题。

### 8.4 批次轮询

- `queued`、`processing`：每 1500ms 请求一次。
- `succeeded`、`partially_succeeded`、`failed`：停止轮询。
- 页面重新获得焦点或网络恢复时立即刷新一次。
- 同一个 `batch_id` 只能存在一个轮询观察者。
- 连续网络失败时采用退避间隔，但不把网络错误误判成任务失败。
- 收到终态后清除 `sessionStorage` 中的活动批次 ID。

### 8.5 任务结果映射

| 后端状态 | 中文文案 | UI 样式 |
| --- | --- | --- |
| `queued` | 等待中 | 中性 |
| `processing` | 处理中 | 进行中 |
| `succeeded` | 处理成功了 | 成功 |
| `failed` | 处理失败 | 错误 |
| `partially_succeeded` | 部分处理成功 | 警告 |

`JobStage` 映射：

- `analyzing`：正在分析视频。
- `synthesizing`：正在生成解说音频。
- `processing`：正在处理和合成视频。
- `completed`：处理完成。

## 9. 校验规则

### 9.1 文件校验

- 至少选择一个视频。
- 扩展名限制为 `.mp4`、`.mov`，大小写不敏感。
- `file.size > 0`。
- 文件过大时最终以服务端 `413` 为准；当前 API 没有暴露大小上限，前端不硬编码一个可能错误的值。
- 前端校验只是即时反馈，服务端仍必须验证文件签名和媒体可解码性。

### 9.2 配置校验

- `output_directory` 去除首尾空格后不能为空。
- `concurrency` 使用无范围限制的数字输入框，提交值必须是整数；服务端自行处理实际并发上限。
- AI 解说关闭时，不提交空的音色和语气字段。
- 允许所有去重开关关闭，但提交前给出确认提示：“当前不会应用去重处理”。
- 不允许把供应商密钥粘贴到任何普通输入框；文案明确提示密钥由后端配置。

## 10. 错误与反馈设计

### 10.1 错误层级

- 字段错误：显示在对应表单控件下方。
- 文件错误：显示在对应文件行。
- 操作错误：在执行区显示可关闭提示。
- 后端不可用：页面顶部持续显示状态条，并禁用开始按钮。
- 未知错误：展示友好文案，同时在开发环境记录原始信息。

### 10.2 API 错误映射

前端统一解析 `{ code, message }`：

- `INVALID_REQUEST`：检查输入配置。
- `FILE_TOO_LARGE`：文件超过后端限制。
- `PROCESSING_FAILED`：媒体处理失败，展示对应 Job 错误。
- 未识别错误码：使用后端 `message`，没有 message 时显示通用错误。

不得展示堆栈、服务端真实内部路径或任何密钥信息。

### 10.3 离开页面保护

上传或处理期间监听 `beforeunload` 并提示用户。该提示只能减少误操作，不能替代后端任务持久化；处理任务应在页面关闭后继续运行。

## 11. 可用性与无障碍

- 所有开关和输入框具有可见 Label。
- 状态不只依赖颜色，同时展示文字或图标。
- 总进度使用原生语义或正确的 `role="progressbar"`、`aria-valuenow`。
- 状态更新区域使用 `aria-live="polite"`，避免每次轮询抢占读屏。
- 错误提示与输入框通过 `aria-describedby` 关联。
- 键盘可完成选择文件以外的全部操作。
- 窄屏下配置区排在文件区之前，主按钮保持容易发现但不遮挡内容。
- 大文件名使用中间省略，悬停或聚焦时可查看完整名称。

## 12. 测试计划

### 12.1 单元测试

- 文件扩展名、空文件和重复文件校验。
- 表单默认值和字段映射。
- `snake_case` API 请求转换。
- 工作流状态机的合法转换。
- 后端状态和中文文案映射。
- 终态停止轮询。
- 刷新后从 `sessionStorage` 恢复批次。

### 12.2 组件测试

- 拖拽和选择多个文件。
- 选择阶段移除文件。
- AI 开关控制附加配置显隐。
- 上传开始后配置和文件列表锁定。
- 双击开始按钮只创建一个工作流。
- 成功任务显示路径、播放和下载入口。
- 部分成功与全部失败的视觉和文案区别。
- 后端不可用时禁止提交。

### 12.3 API Mock 测试

- 上传成功、400、413、断网和超时。
- 创建批次成功、失败和不自动重试。
- `queued → processing → succeeded` 完整轮询。
- 单 Job 失败但批次部分成功。
- 轮询暂时失败后恢复。
- 未识别错误码的降级处理。

### 12.4 E2E 验收

1. 选择两个视频，开启部分去重选项，成功创建批次。
2. 开启 AI 解说并选择 `zh-TW`，请求参数正确。
3. 页面持续展示总进度和逐视频状态。
4. 一个视频失败时，另一个视频仍能成功并下载。
5. 处理期间刷新页面，能够恢复当前批次。
6. 全部成功后每个视频显示“处理成功了”和结果路径。
7. 移动端宽度下没有横向溢出，核心操作可用。

## 13. 开发阶段与工期建议

以下为一名前端开发的建议顺序，工期不包含后端接口等待时间。

### 阶段 0：工程初始化（0.5 天）

- 创建 React + TypeScript + Vite 工程。
- 配置格式化、Lint、测试、路径别名和环境变量。
- 配置开发代理和全局样式变量。
- 接入 OpenAPI 类型生成脚本。

交付标准：前端可启动、构建和执行测试。

### 阶段 1：静态页面和配置表单（1 天）

- 实现页面布局和响应式。
- 实现导出目录、并发数、AI 解说和去重配置。
- 完成默认值、校验、禁用态和基础无障碍。

交付标准：无需后端即可完整操作配置区。

### 阶段 2：文件队列和上传（1 天）

- 实现拖拽、文件选择、列表和删除。
- 实现文件校验和重复提示。
- 实现 XHR multipart 上传、总进度和错误处理。

交付标准：Mock API 下可上传多文件并取得 `upload_ids`。

### 阶段 3：批次创建和进度（1–1.5 天）

- 实现完整工作流 Hook。
- 创建批次并防止重复提交。
- 实现 TanStack Query 轮询、状态恢复和错误退避。
- 映射批次状态到逐视频列表。

交付标准：Mock API 下可走完所有批次状态分支。

### 阶段 4：结果、异常和体验完善（1 天）

- 实现路径复制、视频播放和下载。
- 完成后端不可用、部分成功、处理失败和网络恢复体验。
- 完成离开页面提示、空状态、骨架和反馈文案。

交付标准：核心成功与失败流程均有明确反馈。

### 阶段 5：联调和验收（1–1.5 天）

- 使用真实 API 联调上传、批次和下载。
- 修正 OpenAPI 类型或响应差异。
- 完成组件测试和 E2E。
- 执行响应式、键盘操作和构建产物检查。

交付标准：第 12.4 节所有 E2E 验收通过。

预计前端净开发时间：约 5.5–6.5 人日。

## 14. 后端联调依赖

开发开始前需要后端确认：

1. `POST /uploads/videos` 返回的 `uploads` 顺序是否与上传文件顺序一致。
2. 上传文件大小和数量上限。
3. `output_directory` 是相对路径还是允许受控绝对路径。
4. 批次和 Job 的 `progress` 是否单调递增。
5. 成功 Job 是否始终返回 `artifact_id` 和 `output_path`。
6. 视频下载是否支持浏览器播放所需的 Range 请求。
7. 上传成功但批次未创建时，临时文件的清理策略。
8. 开发和生产环境的 CORS 允许来源。

建议后端后续补充但不阻塞首期的能力：

- 创建批次的幂等键。
- 取消批次接口。
- 失败 Job 重试接口。
- 上传文件删除或自动过期接口。
- 服务能力接口，用于返回文件上限、并发上限和可用音色。

## 15. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 大文件上传耗时长 | 用户误以为卡死 | 持续显示上传百分比、已上传字节和阶段文案 |
| 创建批次超时 | 可能重复创建 | 首期禁止自动重试；后端补充幂等键 |
| 页面刷新导致 File 丢失 | 上传前队列无法恢复 | 上传前刷新提示；只恢复已创建的 `batch_id` |
| 后端状态字段变化 | 页面运行时错误 | OpenAPI 生成类型、Mock 契约测试、联调前重新生成 |
| 浏览器无法选择服务端目录 | 用户理解偏差 | 使用文本输入和明确说明；远程部署改为目录 ID |
| 高频轮询增加请求量 | 后端压力 | 单观察者、终态停止、失败退避、后台标签页降低频率 |
| 视频无法在线播放 | 结果体验下降 | 始终保留下载入口，播放作为增强能力 |

## 16. Definition of Done

- 前端独立启动、测试和生产构建均通过。
- TypeScript 严格模式无错误。
- API 类型由当前 `backend_api.yaml` 生成且无手工漂移。
- 支持至少一个批次包含多个视频。
- 上传、创建批次、轮询、成功、部分成功、失败流程全部覆盖。
- 页面刷新可以恢复已创建且仍在运行的批次。
- 不在前端存储或传输供应商 API Key。
- 核心流程可通过键盘操作，并提供正确状态文本。
- 桌面端和移动端布局通过验收。
- E2E 验收场景全部通过。
