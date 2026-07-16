import type { ApiErrorBody } from './contracts'

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || '/api/v1'
).replace(/\/$/, '')

export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(body: Partial<ApiErrorBody>, status: number) {
    super(body.message || '请求失败，请稍后重试')
    this.name = 'ApiError'
    this.code = body.code || 'UNKNOWN_ERROR'
    this.status = status
  }
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })

  const body = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(body || {}, response.status)
  }
  return body as T
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'FILE_TOO_LARGE') return '文件超过后端允许的大小限制'
    if (error.code === 'INVALID_REQUEST') return '提交内容有误，请检查配置'
    if (error.code === 'PROCESSING_FAILED') return '视频处理失败，请查看任务详情'
    return error.message
  }
  if (error instanceof Error) return error.message
  return '发生未知错误，请稍后重试'
}
