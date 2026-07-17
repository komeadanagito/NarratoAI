import type { VideoJob } from '../../api/contracts'

export type BorderMode = 'none' | 'blurred' | 'solid' | 'asset'

export interface BatchFormValues {
  outputDirectory: string
  concurrency: number
  narration: {
    enabled: boolean
    language: 'zh-CN' | 'zh-TW'
    voiceId: string
    voicePrompt: string
  }
  deduplication: {
    changeFileHash: boolean
    reencode: boolean
    colorNoiseTweak: boolean
    borderMode: BorderMode
    sticker: boolean
    subtitleMask: boolean
    cropScale: boolean
    mirror: boolean
    speedTweak: boolean
  }
}

export type FileStatus = 'selected' | 'uploading' | 'uploaded' | 'failed'

export interface LocalFileItem {
  localId: string
  file: File
  status: FileStatus
  progress: number
  uploadId?: string
  error?: string
}

export interface DisplayVideoItem {
  id: string
  fileName: string
  sizeBytes?: number
  status: FileStatus | VideoJob['status']
  stage?: VideoJob['stage']
  progress: number
  message?: string
  outputPath?: string
  artifactId?: string
  error?: string
}

export type WorkflowPhase =
  | 'idle'
  | 'ready'
  | 'uploading'
  | 'creating_batch'
  | 'processing'
  | 'succeeded'
  | 'partially_succeeded'
  | 'failed'
