import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getBatch } from '../../api/batches'
import { terminalBatchStatuses } from './status'

const ACTIVE_BATCH_KEY = 'narratoai.activeBatchId'

export function getSavedBatchId(): string | null {
  return sessionStorage.getItem(ACTIVE_BATCH_KEY)
}

export function saveBatchId(batchId: string | null) {
  if (batchId) sessionStorage.setItem(ACTIVE_BATCH_KEY, batchId)
  else sessionStorage.removeItem(ACTIVE_BATCH_KEY)
}

export function useBatchPolling(batchId: string | null) {
  const query = useQuery({
    queryKey: ['batch', batchId],
    queryFn: () => getBatch(batchId!),
    enabled: Boolean(batchId),
    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
    refetchInterval: (current) => {
      const status = current.state.data?.batch.status
      if (status && terminalBatchStatuses.has(status)) return false
      return 1500
    },
    refetchIntervalInBackground: false,
  })

  useEffect(() => {
    const status = query.data?.batch.status
    if (status && terminalBatchStatuses.has(status)) saveBatchId(null)
  }, [query.data?.batch.status])

  return query
}
