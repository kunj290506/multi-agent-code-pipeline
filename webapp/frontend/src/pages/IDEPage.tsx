import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { startRun, cancelRun, getRunStatus, getLogs, runProject } from '../api'
import type { RunState } from '../types'
import FileExplorer from '../components/FileExplorer'
import CodeEditor from '../components/CodeEditor'
import ChatPanel from '../components/ChatPanel'

export default function IDEPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [runState, setRunState] = useState<RunState | null>(null)
  // logs kept for future history panel; not yet rendered but fetched to stay fresh
  const [_logs, setLogs] = useState<ReturnType<typeof getLogs> extends Promise<infer T> ? T : never[]>([])
  const [connected, setConnected] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [explorerRefresh, setExplorerRefresh] = useState(0)

  const ws = useRef<WebSocket | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // WebSocket connection
  useEffect(() => {
    const connect = () => {
      ws.current = new WebSocket('ws://localhost:8020/ws')
      ws.current.onopen = () => setConnected(true)
      ws.current.onclose = () => {
        setConnected(false)
        setTimeout(connect, 3000)
      }
      ws.current.onerror = () => ws.current?.close()
      ws.current.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data as string) as { type: string; request_id?: string }
          if (msg?.type === 'file_update') {
            setExplorerRefresh(n => n + 1)
          }
          if (msg?.type === 'project_ready' && msg.request_id) {
            // Auto-run the completed project and open in a new tab
            runProject(msg.request_id).then(result => {
              if (result.runnable && result.url) {
                window.open(result.url, '_blank', 'noopener,noreferrer')
              }
              // If not runnable, the reason will appear in the chat transcript via SSE steps
            }).catch(err => {
              console.error('Failed to auto-run project:', err)
            })
          }
        } catch {
          // ignore non-JSON messages
        }
      }
    }
    connect()
    return () => ws.current?.close()
  }, [])

  // Load run history
  const refreshLogs = useCallback(async () => {
    try {
      const data = await getLogs()
      setLogs(data)
    } catch {
      // backend not ready yet
    }
  }, [])

  useEffect(() => { refreshLogs() }, [refreshLogs])

  // Poll active run status
  useEffect(() => {
    if (!activeRunId) return
    const poll = async () => {
      try {
        const state = await getRunStatus(activeRunId)
        setRunState(state)
        if (state.status !== 'running') {
          if (pollRef.current) clearInterval(pollRef.current)
          pollRef.current = null
          setStopping(false)
          setExplorerRefresh(n => n + 1)
          refreshLogs()
        }
      } catch {
        // ignore transient errors
      }
    }
    poll()
    pollRef.current = setInterval(poll, 1500)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [activeRunId, refreshLogs])

  const isRunning = runState?.status === 'running'

  // Determine active agent for diagram
  const activeAgent: string | null = (() => {
    if (!runState || runState.status !== 'running') return null
    const steps = runState.steps
    if (steps.length === 0) return 'planner-agent'
    const last = steps[steps.length - 1]
    if (last.status === 'done' || last.status === 'failed') {
      const plannerStep = steps.find(s => s.agent === 'planner-agent')
      const subtasks = (plannerStep?.data?.subtasks as Array<{ agent: string }>) ?? []
      const doneAgents = new Set(steps.map(s => s.agent))
      const next = subtasks.find(st => !doneAgents.has(st.agent))
      return next?.agent ?? null
    }
    return last.agent
  })()

  const handleSubmit = async (request: string, projectName: string) => {
    try {
      const data = await startRun(request, projectName || undefined)
      setActiveRunId(data.request_id)
      setRunState(null)
      setStopping(false)
    } catch (err) {
      console.error('Failed to start run', err)
    }
  }

  const handleStop = async () => {
    if (!activeRunId || !isRunning || stopping) return
    setStopping(true)
    try {
      await cancelRun(activeRunId)
    } catch {
      setStopping(false)
    }
  }

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <div className="ide-root">
      {/* Header */}
      <header className="ide-header">
        <div className="ide-brand">
          <div className="ide-brand-accent" />
          <span className="ide-brand-name">Multi-Agent Pipeline</span>
        </div>
        <div className="ide-header-right">
          <div className={`conn-pill ${connected ? 'conn-on' : 'conn-off'}`}>
            <span className="conn-dot" />
            {connected ? 'Connected' : 'Disconnected'}
          </div>
          {user && <span className="ide-user">{user.username}</span>}
          <button className="ide-logout-btn" onClick={handleLogout}>Logout</button>
        </div>
      </header>

      {/* Body — three panes */}
      <div className="ide-body">
        {/* Left pane — file explorer */}
        <div className="ide-pane-left">
          <FileExplorer
            selectedPath={selectedFile}
            onSelect={setSelectedFile}
            refreshTrigger={explorerRefresh}
          />
        </div>

        {/* Center pane — code editor */}
        <div className="ide-pane-center">
          <CodeEditor selectedPath={selectedFile} />
        </div>

        {/* Right pane — chat panel */}
        <div className="ide-pane-right">
          <ChatPanel
            runState={runState}
            isRunning={isRunning}
            onSubmit={handleSubmit}
            activeAgent={activeAgent}
          />
        </div>
      </div>

      {/* STOP button — fixed bottom-right while running */}
      {isRunning && (
        <button
          className="stop-btn"
          onClick={handleStop}
          disabled={stopping}
          aria-label="Stop pipeline run"
        >
          {stopping ? 'Stopping…' : 'Stop'}
        </button>
      )}
    </div>
  )
}
