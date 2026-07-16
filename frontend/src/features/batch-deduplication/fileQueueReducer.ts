import type { LocalFileItem } from './types'

export type FileQueueAction =
  | { type: 'add'; files: File[] }
  | { type: 'remove'; localId: string }
  | { type: 'start_upload' }
  | { type: 'upload_progress'; progress: number }
  | { type: 'upload_complete'; uploadIds: string[] }
  | { type: 'upload_failed'; message: string }
  | { type: 'clear' }

const signature = (file: File) => `${file.name}:${file.size}:${file.lastModified}`

export function fileQueueReducer(
  state: LocalFileItem[],
  action: FileQueueAction,
): LocalFileItem[] {
  switch (action.type) {
    case 'add': {
      const seen = new Set(state.map((item) => signature(item.file)))
      const additions = action.files
        .filter((file) => {
          const key = signature(file)
          if (seen.has(key)) return false
          seen.add(key)
          return true
        })
        .map((file) => ({
          localId: crypto.randomUUID(),
          file,
          status: 'selected' as const,
          progress: 0,
        }))
      return [...state, ...additions]
    }
    case 'remove':
      return state.filter((item) => item.localId !== action.localId)
    case 'start_upload':
      return state.map((item) => ({ ...item, status: 'uploading', progress: 0, error: undefined }))
    case 'upload_progress':
      return state.map((item) =>
        item.status === 'uploading' ? { ...item, progress: action.progress } : item,
      )
    case 'upload_complete':
      return state.map((item, index) => ({
        ...item,
        status: 'uploaded',
        progress: 100,
        uploadId: action.uploadIds[index],
      }))
    case 'upload_failed':
      return state.map((item) =>
        item.status === 'uploading'
          ? { ...item, status: 'failed', error: action.message }
          : item,
      )
    case 'clear':
      return []
  }
}
