import type { BatchFormValues, LocalFileItem } from './types'

const ACCEPTED_EXTENSIONS = ['.mp4', '.mov']

export function validateVideoFile(file: File): string | null {
  const lowerName = file.name.toLowerCase()
  if (!ACCEPTED_EXTENSIONS.some((extension) => lowerName.endsWith(extension))) {
    return '仅支持 MP4 或 MOV 视频'
  }
  if (file.size <= 0) return '文件内容为空'
  return null
}

export function validateFiles(files: File[]): { valid: File[]; errors: string[] } {
  const valid: File[] = []
  const errors: string[] = []
  files.forEach((file) => {
    const error = validateVideoFile(file)
    if (error) errors.push(`${file.name}：${error}`)
    else valid.push(file)
  })
  return { valid, errors }
}

export function validateSubmission(
  values: BatchFormValues,
  files: LocalFileItem[],
): string[] {
  const errors: string[] = []
  if (files.length === 0) errors.push('请至少选择一个视频')
  if (!values.outputDirectory.trim()) errors.push('请填写导出目录')
  if (!Number.isInteger(values.concurrency) || values.concurrency < 1) {
    errors.push('并发线程数必须是大于等于 1 的整数')
  }
  return errors
}

export function hasAnyDeduplication(values: BatchFormValues): boolean {
  const options = values.deduplication
  return (
    options.changeFileHash ||
    options.reencode ||
    options.colorNoiseTweak ||
    options.borderMode !== 'none' ||
    options.sticker ||
    options.subtitleMask ||
    options.cropScale ||
    options.mirror ||
    options.speedTweak
  )
}
