import styles from './Feedback.module.css'

interface FeedbackProps {
  messages: string[]
  onDismiss?: () => void
}

export function Feedback({ messages, onDismiss }: FeedbackProps) {
  if (!messages.length) return null
  return (
    <div className={styles.feedback} role="alert">
      <span className={styles.icon} aria-hidden="true">!</span>
      <div>
        {messages.map((message) => (
          <p key={message}>{message}</p>
        ))}
      </div>
      {onDismiss && (
        <button type="button" onClick={onDismiss} aria-label="关闭提示">×</button>
      )}
    </div>
  )
}
