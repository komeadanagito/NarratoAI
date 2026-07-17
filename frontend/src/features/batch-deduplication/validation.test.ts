import { describe, expect, it } from 'vitest'
import { defaultFormValues } from './configReducer'
import { validateFiles, validateSubmission, validateVideoFile } from './validation'

const video = (name: string, content = 'video') =>
  new File([content], name, { type: 'video/mp4', lastModified: 1 })

describe('video validation', () => {
  it('accepts MP4 and MOV case-insensitively', () => {
    expect(validateVideoFile(video('a.MP4'))).toBeNull()
    expect(validateVideoFile(video('b.mov'))).toBeNull()
  })

  it('rejects unsupported and empty files with per-file messages', () => {
    const result = validateFiles([
      video('notes.txt'),
      new File([], 'empty.mp4', { type: 'video/mp4' }),
    ])
    expect(result.valid).toHaveLength(0)
    expect(result.errors).toEqual([
      'notes.txt：仅支持 MP4 或 MOV 视频',
      'empty.mp4：文件内容为空',
    ])
  })
})

describe('submission validation', () => {
  it('requires files, an output directory, and valid concurrency', () => {
    const values = { ...defaultFormValues, outputDirectory: ' ', concurrency: 1.5 }
    expect(validateSubmission(values, [])).toEqual([
      '请至少选择一个视频',
      '请填写导出目录',
      '并发线程数必须是大于等于 1 的整数',
    ])
  })

  it('rejects zero concurrency without imposing an upper limit', () => {
    const files = [
      {
        localId: '1',
        file: video('demo.mp4'),
        status: 'selected' as const,
        progress: 0,
      },
    ]

    expect(
      validateSubmission({ ...defaultFormValues, concurrency: 0 }, files),
    ).toContain('并发线程数必须是大于等于 1 的整数')
    expect(
      validateSubmission({ ...defaultFormValues, concurrency: 100_000 }, files),
    ).toEqual([])
  })
})
