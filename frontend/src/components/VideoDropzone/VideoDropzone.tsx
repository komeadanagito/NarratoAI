import { useRef, useState } from 'react'
import styles from './VideoDropzone.module.css'

interface VideoDropzoneProps {
  disabled: boolean
  onFiles: (files: File[]) => void
}

export function VideoDropzone({ disabled, onFiles }: VideoDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  return (
    <div
      className={`${styles.dropzone} ${dragging ? styles.dragging : ''} ${disabled ? styles.disabled : ''}`}
      onDragEnter={(event) => {
        event.preventDefault()
        if (!disabled) setDragging(true)
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false)
      }}
      onDrop={(event) => {
        event.preventDefault()
        setDragging(false)
        if (!disabled) onFiles(Array.from(event.dataTransfer.files))
      }}
    >
      <input
        ref={inputRef}
        className={styles.input}
        type="file"
        accept=".mp4,.mov,video/mp4,video/quicktime"
        multiple
        disabled={disabled}
        aria-label="选择视频文件"
        onChange={(event) => {
          if (event.target.files) onFiles(Array.from(event.target.files))
          event.target.value = ''
        }}
      />
      <button
        type="button"
        className={styles.chooseButton}
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        <span className={styles.addIcon} aria-hidden="true">＋</span>
        选择视频文件
      </button>
      <div className={styles.copy}>
        <strong>或将多个视频拖放到这里</strong>
        <span>支持 MP4、MOV · 点击开始后统一上传</span>
      </div>
    </div>
  )
}
