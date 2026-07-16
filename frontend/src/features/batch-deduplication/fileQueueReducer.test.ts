import { describe, expect, it, vi } from 'vitest'
import { fileQueueReducer } from './fileQueueReducer'

describe('fileQueueReducer', () => {
  it('deduplicates the same file signature and preserves distinct files', () => {
    vi.spyOn(crypto, 'randomUUID')
      .mockReturnValueOnce('00000000-0000-4000-8000-000000000001')
      .mockReturnValueOnce('00000000-0000-4000-8000-000000000002')
    const first = new File(['a'], 'clip.mp4', { lastModified: 1 })
    const duplicate = new File(['a'], 'clip.mp4', { lastModified: 1 })
    const second = new File(['bb'], 'clip.mp4', { lastModified: 2 })

    const state = fileQueueReducer([], { type: 'add', files: [first, duplicate, second] })
    expect(state).toHaveLength(2)
    expect(state.map((item) => item.localId)).toEqual([
      '00000000-0000-4000-8000-000000000001',
      '00000000-0000-4000-8000-000000000002',
    ])
  })
})
