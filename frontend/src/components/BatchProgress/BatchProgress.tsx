import type { Batch } from '../../api/contracts'
import { batchStatusLabel } from '../../features/batch-deduplication/status'
import styles from './BatchProgress.module.css'

interface BatchProgressProps {
  batch: Batch
  fetching: boolean
}

export function BatchProgress({ batch, fetching }: BatchProgressProps) {
  return (
    <section className={styles.card} aria-live="polite">
      <div className={styles.topline}>
        <div>
          <span className={styles.kicker}>BATCH PROGRESS</span>
          <h3>{batchStatusLabel[batch.status]}</h3>
        </div>
        <div className={styles.percent}>{batch.progress}<small>%</small></div>
      </div>
      <div
        className={styles.track}
        role="progressbar"
        aria-label="批次处理进度"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={batch.progress}
      >
        <span style={{ width: `${batch.progress}%` }} />
      </div>
      <div className={styles.meta}>
        <span>共 {batch.total} 个视频</span>
        <span className={styles.success}>成功 {batch.succeeded}</span>
        <span className={batch.failed ? styles.failed : ''}>失败 {batch.failed}</span>
        {fetching && <span className={styles.sync}>同步中</span>}
      </div>
    </section>
  )
}
