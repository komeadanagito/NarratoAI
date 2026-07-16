import { describe, expect, it } from 'vitest'
import { createBatch, getBatch, getHealth } from './batches'
import { defaultFormValues, toBatchCreateRequest } from '../features/batch-deduplication/configReducer'

describe('batch API', () => {
  it('checks backend health through the configured base URL', async () => {
    await expect(getHealth()).resolves.toEqual({ status: 'ok' })
  })

  it('creates and reads a batch through mocked HTTP endpoints', async () => {
    const created = await createBatch(
      toBatchCreateRequest(defaultFormValues, [
        '7299805d-e188-481e-9ef4-f6915af55bd0',
      ]),
    )
    expect(created.batch.status).toBe('queued')
    await expect(getBatch(created.batch.id)).resolves.toMatchObject({
      batch: { total: 1, jobs: [{ file_name: 'sample.mp4' }] },
    })
  })
})
