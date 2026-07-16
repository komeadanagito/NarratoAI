import { http, HttpResponse } from 'msw'

export const queuedBatchResponse = {
  batch: {
    id: '18d3b5c1-c853-4b95-a333-f2011f86a277',
    status: 'queued' as const,
    progress: 0,
    total: 1,
    succeeded: 0,
    failed: 0,
    jobs: [
      {
        id: '090df874-68aa-419e-87b8-114ff64ab22f',
        upload_id: '7299805d-e188-481e-9ef4-f6915af55bd0',
        file_name: 'sample.mp4',
        status: 'queued' as const,
        stage: 'queued' as const,
        progress: 0,
      },
    ],
  },
}

export const handlers = [
  http.get('http://localhost/api/v1/health', () => HttpResponse.json({ status: 'ok' })),
  http.post('http://localhost/api/v1/batches', () =>
    HttpResponse.json(queuedBatchResponse, { status: 202 }),
  ),
  http.get('http://localhost/api/v1/batches/:batchId', () =>
    HttpResponse.json(queuedBatchResponse),
  ),
]
