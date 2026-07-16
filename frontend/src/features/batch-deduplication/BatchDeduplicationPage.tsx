import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getHealth } from '../../api/batches'
import { getErrorMessage } from '../../api/client'
import { BatchProgress } from '../../components/BatchProgress/BatchProgress'
import { ConfigPanel } from '../../components/ConfigPanel/ConfigPanel'
import { Feedback } from '../../components/Feedback/Feedback'
import { VideoDropzone } from '../../components/VideoDropzone/VideoDropzone'
import { VideoList } from '../../components/VideoList/VideoList'
import type { DisplayVideoItem } from './types'
import { useBatchWorkflow } from './useBatchWorkflow'
import styles from './BatchDeduplicationPage.module.css'

const phaseButtonText = {
  idle: '开始批量处理',
  ready: '开始批量处理',
  uploading: '正在上传视频…',
  creating_batch: '正在创建批次…',
  processing: '正在批量处理…',
  succeeded: '处理新的批次',
  partially_succeeded: '处理新的批次',
  failed: '处理新的批次',
} as const

export function BatchDeduplicationPage() {
  const workflow = useBatchWorkflow()
  const health = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    retry: false,
    refetchInterval: 10_000,
  })

  const displayItems = useMemo<DisplayVideoItem[]>(() => {
    if (workflow.batch) {
      return workflow.batch.jobs.map((job) => ({
        id: job.id,
        fileName: job.file_name,
        status: job.status,
        stage: job.stage,
        progress: job.progress,
        message: job.message,
        outputPath: job.output_path,
        artifactId: job.artifact_id,
        error: job.error?.message,
      }))
    }
    return workflow.files.map((item) => ({
      id: item.localId,
      fileName: item.file.name,
      sizeBytes: item.file.size,
      status: item.status,
      progress: item.progress,
      error: item.error,
    }))
  }, [workflow.batch, workflow.files])

  const terminal =
    workflow.phase === 'succeeded' ||
    workflow.phase === 'partially_succeeded' ||
    workflow.phase === 'failed'
  const backendUnavailable = health.isError
  const batchError = workflow.batchError ? [getErrorMessage(workflow.batchError)] : []

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>N</span>
          <span>
            <strong>NarratoAI</strong>
            <small>视频批处理工具</small>
          </span>
        </div>
        <div className={styles.serviceState}>
          <span className={backendUnavailable ? styles.offline : styles.online} />
          {health.isPending ? '正在连接服务' : backendUnavailable ? '后端服务不可用' : '服务已连接'}
        </div>
      </header>

      <section className={styles.pageTitle}>
        <h1>批量视频处理</h1>
        <p>
          批量完成视频处理，可选 AI 解说、配音与字幕合成。
        </p>
      </section>

      {backendUnavailable && (
        <div className={styles.connectionWarning} role="alert">
          无法连接后端服务，请确认 NarratoAI API 已在 127.0.0.1:8080 启动。
        </div>
      )}

      <div className={styles.workspace}>
        <div className={styles.configColumn}>
          <ConfigPanel
            values={workflow.config}
            dispatch={workflow.dispatchConfig}
            disabled={workflow.locked}
          />
        </div>

        <section className={styles.executionPanel} aria-label="视频与执行">
          <div className={styles.panelHeader}>
            <h2>视频文件</h2>
            <div className={styles.count}>
              <strong>{displayItems.length}</strong>
              <span>个视频</span>
            </div>
          </div>

          {!workflow.batch && (
            <VideoDropzone disabled={workflow.locked} onFiles={workflow.addFiles} />
          )}

          <Feedback
            messages={[...workflow.feedback, ...batchError]}
            onDismiss={() => workflow.setFeedback([])}
          />

          {workflow.batch && (
            <BatchProgress batch={workflow.batch} fetching={workflow.batchFetching} />
          )}

          <div className={styles.listHeader}>
            <span>视频列表</span>
            <span>{workflow.batch ? '实时处理状态' : '选择后不会立即上传'}</span>
          </div>
          <div className={styles.listArea}>
            <VideoList
              items={displayItems}
              removable={!workflow.locked && !workflow.batch}
              onRemove={(localId) => workflow.dispatchFiles({ type: 'remove', localId })}
            />
          </div>

          <footer className={styles.actionBar}>
            <div className={styles.actionHint}>
              <span aria-hidden="true">i</span>
              <p>
                {terminal
                  ? '本批次已结束，可保留结果并开始处理新文件。'
                  : '处理期间可以离开当前标签页，后端任务会继续运行。'}
              </p>
            </div>
            {terminal ? (
              <button type="button" className={styles.primaryButton} onClick={workflow.reset}>
                {phaseButtonText[workflow.phase]}
              </button>
            ) : (
              <button
                type="button"
                className={styles.primaryButton}
                disabled={!workflow.canStart || !health.isSuccess}
                onClick={() => void workflow.start()}
              >
                {phaseButtonText[workflow.phase]}
              </button>
            )}
          </footer>
        </section>
      </div>

      <footer className={styles.pageFooter}>
        <span>本地视频处理工作台</span>
        <span>API 密钥仅保存在服务端</span>
      </footer>
    </main>
  )
}
