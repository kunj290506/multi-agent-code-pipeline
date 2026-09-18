import { useEffect, useRef, useState } from 'react'
import { BASE } from '../api'

interface TerminalPanelProps {
  projectId: string | null
}

interface TerminalEvent {
  type: string
  stream: string
  line: string
}

export default function TerminalPanel({ projectId }: TerminalPanelProps) {
  const [lines, setLines] = useState<{ stream: string; line: string }[]>([])
  const [connected, setConnected] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!projectId) {
      setLines([])
      setConnected(false)
      return
    }

    setLines([])
    const eventSource = new EventSource(`${BASE}/projects/${projectId}/terminal`, {
      withCredentials: true,
    })

    eventSource.onopen = () => {
      setConnected(true)
    }

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as TerminalEvent
        if (data.type === 'terminal_output') {
          setLines(prev => {
            const next = [...prev, { stream: data.stream, line: data.line }]
            return next.slice(-500) // 500-line ring buffer
          })
        }
      } catch (err) {
        console.error('Failed to parse terminal event', err)
      }
    }

    eventSource.onerror = () => {
      setConnected(false)
      // SSE automatically attempts reconnect, but if it fails repeatedly we just stay disconnected
    }

    return () => {
      eventSource.close()
      setConnected(false)
    }
  }, [projectId])

  // Auto-scroll to bottom
  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView() // no smooth scrolling for terminal, keep it snappy
    }
  }, [lines.length])

  if (!projectId) {
    return (
      <div className="terminal-placeholder">
        No project running.
      </div>
    )
  }

  return (
    <div className="terminal-panel">
      <div className="terminal-header">
        <div className="terminal-title">TERMINAL</div>
        <div className={`conn-pill ${connected ? 'conn-on' : 'conn-off'}`}>
          <span className="conn-dot" />
          {connected ? 'Connected' : 'Disconnected'}
        </div>
      </div>
      <div className="terminal-output">
        {lines.length === 0 && connected && (
          <div className="terminal-placeholder">Waiting for output...</div>
        )}
        {lines.map((l, i) => (
          <div key={i} className={`terminal-line terminal-${l.stream}`}>
            {l.line}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
