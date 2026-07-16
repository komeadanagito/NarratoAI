# NarratoAI Frontend

批量视频处理与 AI 解说单页面前端。接口契约来自 `../docs/backend_api.yaml`。

## 本地开发

```bash
npm install
npm run dev
```

默认访问 `http://127.0.0.1:5173`，开发服务器会把 `/api` 转发到
`http://127.0.0.1:8080`。

如需连接其他后端，复制 `.env.example` 为 `.env.local` 并修改
`VITE_API_BASE_URL`。

## 验证

```bash
npm run generate:api
npm run typecheck
npm test
npm run build
```

`src/api/generated.ts` 由 OpenAPI 自动生成，不要手工修改。
