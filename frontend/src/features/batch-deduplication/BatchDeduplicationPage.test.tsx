import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BatchDeduplicationPage } from './BatchDeduplicationPage'

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <BatchDeduplicationPage />
    </QueryClientProvider>,
  )
}

describe('BatchDeduplicationPage', () => {
  it('connects to the backend and adds valid selected videos to the queue', async () => {
    renderPage()
    expect(await screen.findByText('服务已连接')).toBeInTheDocument()

    const input = screen.getByLabelText('选择视频文件')
    const file = new File(['video'], 'demo.mp4', { type: 'video/mp4' })
    fireEvent.change(input, { target: { files: [file] } })

    expect(screen.getByText('demo.mp4')).toBeInTheDocument()
    expect(screen.getByText('已选择')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /开始批量处理/ })).toBeEnabled()
  })

  it('shows validation feedback for an unsupported file', async () => {
    renderPage()
    await screen.findByText('服务已连接')
    const file = new File(['text'], 'demo.txt', { type: 'text/plain' })
    fireEvent.change(screen.getByLabelText('选择视频文件'), {
      target: { files: [file] },
    })
    expect(screen.getByRole('alert')).toHaveTextContent('仅支持 MP4 或 MOV 视频')
  })
})
