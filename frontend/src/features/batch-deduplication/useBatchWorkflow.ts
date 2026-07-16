import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { createBatch } from '../../api/batches'
import { getErrorMessage } from '../../api/client'
import type { BatchResponse } from '../../api/contracts'
import { uploadVideos } from '../../api/uploads'
import { configReducer, defaultFormValues, toBatchCreateRequest } from './configReducer'
import { fileQueueReducer } from './fileQueueReducer'
import type { WorkflowPhase } from './types'
import { getSavedBatchId, saveBatchId, useBatchPolling } from './useBatchPolling'
import { hasAnyDeduplication, validateFiles, validateSubmission } from './validation'

export function useBatchWorkflow() {
  const [config, dispatchConfig] = useReducer(configReducer, defaultFormValues)
  const [files, dispatchFiles] = useReducer(fileQueueReducer, [])
  const [batchId, setBatchId] = useState<string | null>(() => getSavedBatchId())
  const [phase, setPhase] = useState<WorkflowPhase>(() =>
    getSavedBatchId() ? 'processing' : 'idle',
  )
  const [feedback, setFeedback] = useState<string[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const queryClient = useQueryClient()
  const batchQuery = useBatchPolling(batchId)
  const batch = batchQuery.data?.batch

  useEffect(() => {
    if (!batch) return
    if (
      batch.status === 'succeeded' ||
      batch.status === 'partially_succeeded' ||
      batch.status === 'failed'
    ) {
      setPhase(batch.status)
    } else {
      setPhase('processing')
    }
  }, [batch])

  useEffect(() => {
    const active = phase === 'uploading' || phase === 'creating_batch' || phase === 'processing'
    if (!active) return
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [phase])

  const addFiles = useCallback((incoming: File[]) => {
    const result = validateFiles(incoming)
    dispatchFiles({ type: 'add', files: result.valid })
    setFeedback(result.errors)
    if (result.valid.length) setPhase('ready')
  }, [])

  const start = useCallback(async () => {
    const errors = validateSubmission(config, files)
    if (!hasAnyDeduplication(config) && !config.narration.enabled) {
      errors.push('请至少启用 AI 解说或一项视频处理功能')
    }
    if (errors.length) {
      setFeedback(errors)
      return
    }

    setFeedback([])
    setPhase('uploading')
    dispatchFiles({ type: 'start_upload' })
    const abortController = new AbortController()
    abortRef.current = abortController

    try {
      const uploadResponse = await uploadVideos(
        files.map((item) => item.file),
        {
          signal: abortController.signal,
          onProgress: (progress) => dispatchFiles({ type: 'upload_progress', progress }),
        },
      )
      if (uploadResponse.uploads.length !== files.length) {
        throw new Error('后端返回的上传文件数量与选择数量不一致')
      }
      const uploadIds = uploadResponse.uploads.map((upload) => upload.id)
      dispatchFiles({ type: 'upload_complete', uploadIds })
      setPhase('creating_batch')
      const response = await createBatch(toBatchCreateRequest(config, uploadIds))
      const nextBatchId = response.batch.id
      queryClient.setQueryData<BatchResponse>(['batch', nextBatchId], response)
      saveBatchId(nextBatchId)
      setBatchId(nextBatchId)
      setPhase('processing')
    } catch (error) {
      const message = getErrorMessage(error)
      dispatchFiles({ type: 'upload_failed', message })
      setFeedback([message])
      setPhase('ready')
    } finally {
      abortRef.current = null
    }
  }, [config, files, queryClient])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    saveBatchId(null)
    setBatchId(null)
    setFeedback([])
    dispatchFiles({ type: 'clear' })
    setPhase('idle')
  }, [])

  const locked = phase === 'uploading' || phase === 'creating_batch' || phase === 'processing'
  const canStart = files.length > 0 && !locked && !batchId

  return useMemo(
    () => ({
      config,
      dispatchConfig,
      files,
      dispatchFiles,
      addFiles,
      start,
      reset,
      phase,
      feedback,
      setFeedback,
      batch,
      batchError: batchQuery.error,
      batchFetching: batchQuery.isFetching,
      locked,
      canStart,
    }),
    [
      config,
      files,
      addFiles,
      start,
      reset,
      phase,
      feedback,
      batch,
      batchQuery.error,
      batchQuery.isFetching,
      locked,
      canStart,
    ],
  )
}
