import { getArtifactUrl } from '../../api/artifacts'
import { jobStatusLabel, stageLabel } from '../../features/batch-deduplication/status'
import type { DisplayVideoItem } from '../../features/batch-deduplication/types'
import styles from './VideoList.module.css'

interface VideoListProps {
  items: DisplayVideoItem[]
  removable: boolean
  onRemove: (id: string) => void
}

const localStatusLabel: Record<string, string> = {
  selected: '已选择',
  uploading: '上传中',
  uploaded: '上传完成',
  failed: '失败',
}

function formatBytes(value?: number) {
  if (value === undefined) return '—'
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function statusText(item: DisplayVideoItem) {
  if (item.status in jobStatusLabel) return jobStatusLabel[item.status as keyof typeof jobStatusLabel]
  return localStatusLabel[item.status] || item.status
}

export function VideoList({ items, removable, onRemove }: VideoListProps) {
  if (!items.length) {
    return (
      <div className={styles.empty}>
        <span aria-hidden="true">00</span>
        <strong>等待添加视频</strong>
        <p>选择后将在这里展示文件和处理状态</p>
      </div>
    )
  }

  return (
    <div className={styles.list} aria-live="polite">
      {items.map((item, index) => {
        const isSuccess = item.status === 'succeeded'
        const isFailed = item.status === 'failed'
        const stateClass = isSuccess ? styles.success : isFailed ? styles.failed : ''
        return (
          <article className={`${styles.row} ${stateClass}`} key={item.id}>
            <div className={styles.index}>{String(index + 1).padStart(2, '0')}</div>
            <div className={styles.fileInfo}>
              <strong title={item.fileName}>{item.fileName}</strong>
              <span>
                {item.stage ? stageLabel[item.stage] : formatBytes(item.sizeBytes)}
                {item.message && ` · ${item.message}`}
              </span>
              {(item.status === 'uploading' || item.status === 'processing') && (
                <div className={styles.miniTrack}>
                  <span style={{ width: `${item.progress}%` }} />
                </div>
              )}
              {item.error && <p className={styles.error}>{item.error}</p>}
              {item.outputPath && (
                <button
                  type="button"
                  className={styles.path}
                  title="复制输出路径"
                  onClick={() => void navigator.clipboard.writeText(item.outputPath!)}
                >
                  {item.outputPath}
                </button>
              )}
            </div>
            <div className={styles.actions}>
              <span className={styles.status}>{statusText(item)}</span>
              {item.artifactId && (
                <>
                  <a
                    className={styles.download}
                    href={getArtifactUrl(item.artifactId)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    播放
                  </a>
                  <a
                    className={styles.download}
                    href={getArtifactUrl(item.artifactId)}
                    download
                  >
                    下载
                  </a>
                </>
              )}
              {removable && (
                <button
                  className={styles.remove}
                  type="button"
                  aria-label={`移除 ${item.fileName}`}
                  onClick={() => onRemove(item.id)}
                >
                  ×
                </button>
              )}
            </div>
          </article>
        )
      })}
    </div>
  )
}
