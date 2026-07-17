import type { Dispatch } from 'react'
import type { ConfigAction } from '../../features/batch-deduplication/configReducer'
import type { BatchFormValues } from '../../features/batch-deduplication/types'
import styles from './ConfigPanel.module.css'

interface ConfigPanelProps {
  values: BatchFormValues
  dispatch: Dispatch<ConfigAction>
  disabled: boolean
}

interface ToggleProps {
  label: string
  description: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled: boolean
}

function Toggle({ label, description, checked, onChange, disabled }: ToggleProps) {
  return (
    <label className={`${styles.toggle} ${checked ? styles.toggleActive : ''}`}>
      <span>
        <strong>{label}</strong>
        <small>{description}</small>
      </span>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className={styles.switch} aria-hidden="true" />
    </label>
  )
}

export function ConfigPanel({ values, dispatch, disabled }: ConfigPanelProps) {
  const set = (path: string, value: string | number | boolean) =>
    dispatch({ type: 'set', path, value })
  const dedup = values.deduplication

  return (
    <aside className={styles.panel} aria-label="处理配置">
      <div className={styles.panelHeader}>
        <h2>处理配置</h2>
      </div>

      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <h3>输出与性能</h3>
          <span>必填</span>
        </div>
        <label className={styles.field}>
          <span>导出目录</span>
          <input
            value={values.outputDirectory}
            disabled={disabled}
            placeholder="./storage/outputs"
            onChange={(event) => set('outputDirectory', event.target.value)}
          />
          <small>这是后端服务可访问的路径，不是浏览器下载目录。</small>
        </label>
        <label className={styles.field}>
          <span>并发线程数</span>
          <input
            type="number"
            min="1"
            step="1"
            value={values.concurrency}
            disabled={disabled}
            onChange={(event) => set('concurrency', Number(event.target.value))}
          />
          <small>填写需要同时处理的视频数量。</small>
        </label>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <h3>AI 解说配音</h3>
          <span>可选</span>
        </div>
        <Toggle
          label="启用 AI 自动解说"
          description="自动分析画面、生成文案、配音并压入字幕"
          checked={values.narration.enabled}
          disabled={disabled}
          onChange={(checked) => set('narration.enabled', checked)}
        />
        {values.narration.enabled && (
          <div className={styles.narrationFields}>
            <label className={styles.field}>
              <span>解说语言 / 口音</span>
              <select
                value={values.narration.language}
                disabled={disabled}
                onChange={(event) => set('narration.language', event.target.value)}
              >
                <option value="zh-CN">普通话</option>
                <option value="zh-TW">台湾口音</option>
              </select>
            </label>
            <label className={styles.field}>
              <span>音色 ID（可选）</span>
              <input
                value={values.narration.voiceId}
                disabled={disabled}
                placeholder="使用服务端默认音色"
                onChange={(event) => set('narration.voiceId', event.target.value)}
              />
            </label>
            <label className={styles.field}>
              <span>语气描述（可选）</span>
              <textarea
                rows={3}
                maxLength={500}
                value={values.narration.voicePrompt}
                disabled={disabled}
                placeholder="例如：成熟、克制、略带悬疑感"
                onChange={(event) => set('narration.voicePrompt', event.target.value)}
              />
            </label>
          </div>
        )}
      </section>

      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <h3>视频处理选项</h3>
          <span>按需开启</span>
        </div>
        <div className={styles.toggleList}>
          <Toggle
            label="修改文件哈希"
            description="改变输出文件的二进制摘要"
            checked={dedup.changeFileHash}
            disabled={disabled}
            onChange={(value) => set('deduplication.changeFileHash', value)}
          />
          <Toggle
            label="重新编码视频"
            description="强制重建视频流和编码结构"
            checked={dedup.reencode}
            disabled={disabled}
            onChange={(value) => set('deduplication.reencode', value)}
          />
          <Toggle
            label="画面参数与轻微噪点"
            description="微调亮度、对比度、饱和度和像素噪点"
            checked={dedup.colorNoiseTweak}
            disabled={disabled}
            onChange={(value) => set('deduplication.colorNoiseTweak', value)}
          />

          <label className={styles.field}>
            <span>随机边框</span>
            <select
              value={dedup.borderMode}
              disabled={disabled}
              onChange={(event) => set('deduplication.borderMode', event.target.value)}
            >
              <option value="none">不添加</option>
              <option value="blurred">模糊背景</option>
              <option value="solid">纯色边框</option>
              <option value="asset">素材边框（随机）</option>
            </select>
          </label>

          <Toggle
            label="随机贴图"
            description="在非主体区域随机叠加透明贴图"
            checked={dedup.sticker}
            disabled={disabled}
            onChange={(value) => set('deduplication.sticker', value)}
          />
          <Toggle
            label="字幕蒙版"
            description="柔化遮罩原视频底部字幕区域"
            checked={dedup.subtitleMask}
            disabled={disabled}
            onChange={(value) => set('deduplication.subtitleMask', value)}
          />
          <Toggle
            label="随机裁剪 / 缩放"
            description="由服务端在安全范围内轻微调整画幅"
            checked={dedup.cropScale}
            disabled={disabled}
            onChange={(value) => set('deduplication.cropScale', value)}
          />
          <Toggle
            label="随机水平镜像"
            description="随机决定是否翻转画面"
            checked={dedup.mirror}
            disabled={disabled}
            onChange={(value) => set('deduplication.mirror', value)}
          />
          <Toggle
            label="随机播放速率"
            description="同步微调视频和音频播放速度"
            checked={dedup.speedTweak}
            disabled={disabled}
            onChange={(value) => set('deduplication.speedTweak', value)}
          />
        </div>
      </section>
    </aside>
  )
}
