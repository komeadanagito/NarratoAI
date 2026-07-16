import type { BatchStatus, JobStage, JobStatus } from '../../api/contracts'

export const terminalBatchStatuses = new Set<BatchStatus>([
  'succeeded',
  'partially_succeeded',
  'failed',
])

export const jobStatusLabel: Record<JobStatus, string> = {
  queued: '等待中',
  processing: '处理中',
  succeeded: '处理成功了',
  failed: '处理失败',
}

export const stageLabel: Record<JobStage, string> = {
  queued: '等待调度',
  analyzing: '正在分析视频',
  synthesizing: '正在生成解说音频',
  processing: '正在处理和合成视频',
  completed: '处理完成',
}

export const batchStatusLabel: Record<BatchStatus, string> = {
  queued: '等待开始',
  processing: '批量处理中',
  succeeded: '全部处理完成',
  partially_succeeded: '部分处理成功',
  failed: '批次处理失败',
}
