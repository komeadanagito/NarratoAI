import { API_BASE_URL, ApiError } from './client'
import type { UploadsResponse } from './contracts'

interface UploadOptions {
  onProgress?: (progress: number, loaded: number, total: number) => void
  signal?: AbortSignal
}

export function uploadVideos(
  files: File[],
  options: UploadOptions = {},
): Promise<UploadsResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const body = new FormData()
    files.forEach((file) => body.append('files', file, file.name))

    xhr.open('POST', `${API_BASE_URL}/uploads/videos`)
    xhr.responseType = 'json'

    xhr.upload.addEventListener('progress', (event) => {
      if (!event.lengthComputable) return
      options.onProgress?.(
        Math.round((event.loaded / event.total) * 100),
        event.loaded,
        event.total,
      )
    })

    xhr.addEventListener('load', () => {
      const response = xhr.response as UploadsResponse | { code?: string; message?: string } | null
      if (xhr.status >= 200 && xhr.status < 300 && response && 'uploads' in response) {
        resolve(response)
        return
      }
      const errorBody = response && 'code' in response ? response : {}
      reject(new ApiError(errorBody, xhr.status))
    })
    xhr.addEventListener('error', () => reject(new Error('网络连接失败，视频未上传')))
    xhr.addEventListener('abort', () => reject(new DOMException('上传已中止', 'AbortError')))
    xhr.addEventListener('timeout', () => reject(new Error('上传超时，请检查网络后重试')))

    const abort = () => xhr.abort()
    options.signal?.addEventListener('abort', abort, { once: true })
    xhr.addEventListener('loadend', () => options.signal?.removeEventListener('abort', abort))
    xhr.send(body)
  })
}
