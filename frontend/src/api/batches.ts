import { requestJson } from './client'
import type { BatchCreateRequest, BatchResponse } from './contracts'

export function createBatch(request: BatchCreateRequest): Promise<BatchResponse> {
  return requestJson('/batches', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export function getBatch(batchId: string): Promise<BatchResponse> {
  return requestJson(`/batches/${encodeURIComponent(batchId)}`)
}

export function getHealth(): Promise<{ status: 'ok' }> {
  return requestJson('/health')
}
