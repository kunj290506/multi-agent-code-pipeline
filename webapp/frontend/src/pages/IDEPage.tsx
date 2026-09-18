import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { startRun, cancelRun, getRunStatus, getLogs, getLog, runProject, approvePlan } from '../api'
import type { RunState, Subtask } from '../types'
import FileExplorer from '../components/FileExplorer'
import ProjectHistory from '../components/ProjectHistory'
import CodeEditor from '../components/CodeEditor'
import ChatPanel from '../components/ChatPanel'
import TerminalPanel from '../components/TerminalPanel'

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
  const [diffData, setDiffData] = useState<{ filename: string; previous_content: string | null; new_content: string } | null>(null)

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
          const msg = JSON.parse(evt.data as string) as {
            type: string;
            request_id?: string;
            filename?: string;
            previous_content?: string | null;
            new_content?: string;
          }
          if (msg?.type === 'file_update' || msg?.type === 'file_delete') {
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
          // Capture file_written events for diff view
          if (msg?.type === 'file_written' && msg.filename && msg.new_content !== undefined) {
            setDiffData({
              filename: msg.filename,
              previous_content: msg.previous_content ?? null,
              new_content: msg.new_content,
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
        if (state.status !== 'running' && state.status !== 'awaiting_approval') {
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
    if (!runState || (runState.status !== 'running' && runState.status !== 'awaiting_approval')) return null
    if (runState.status === 'awaiting_approval') return 'planner-agent'
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
      const isFollowUp = !projectName && activeRunId
      const projectIdToPass = isFollowUp ? activeRunId : undefined
      
      const data = await startRun(request, projectName || undefined, projectIdToPass)
      setActiveRunId(data.request_id)
      setRunState(null)
      setStopping(false)
      if (!isFollowUp) {
        setSelectedFile(null)          // clear editor — workspace is wiping
      }
      setExplorerRefresh(n => n + 1) // immediately refresh explorer
    } catch (err) {
      console.error('Failed to start run', err)
    }
  }

  const handleSelectProject = async (projectId: string) => {
    setActiveRunId(projectId)
    setSelectedFile(null)
    setExplorerRefresh(n => n + 1)
    try {
      // First try live status in case it's still running
      const state = await getRunStatus(projectId)
      setRunState(state)
    } catch {
      // If not live, fetch from logs
      try {
        const log = await getLog(projectId)
        setRunState(log)
      } catch (err) {
        console.error('Failed to load project log', err)
        setRunState(null)
      }
    }
  }

  const handleStop = async () => {
    if (!activeRunId || stopping) return
    // Allow stopping during both 'running' and 'awaiting_approval'
    if (runState?.status !== 'running' && runState?.status !== 'awaiting_approval') return
    setStopping(true)
    try {
      await cancelRun(activeRunId)
    } catch {
      setStopping(false)
    }
  }

  const handleApprove = async (subtasks: Subtask[]) => {
    if (!activeRunId) return
    try {
      await approvePlan(activeRunId, subtasks as unknown as Array<Record<string, unknown>>)
    } catch (err) {
      console.error('Failed to approve plan', err)
    }
  }

  const handleCancel = () => {
    handleStop()
  }

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  const showStopButton = runState?.status === 'running' || runState?.status === 'awaiting_approval'

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
        {/* Left pane — project history + file explorer */}
        <div className="ide-pane-left" style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ height: '35%', minHeight: '200px' }}>
            <ProjectHistory
              activeProjectId={activeRunId}
              onSelectProject={handleSelectProject}
            />
          </div>
          <div style={{ flex: 1, minHeight: 0, borderTop: '1px solid var(--hairline)' }}>
            <FileExplorer
              selectedPath={selectedFile}
              onSelect={setSelectedFile}
              refreshTrigger={explorerRefresh}
              projectId={activeRunId ?? undefined}
            />
          </div>
        </div>

        {/* Center pane — code editor + terminal */}
        <div className="ide-pane-center" style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, minHeight: 0 }}>
            <CodeEditor selectedPath={selectedFile} diffData={diffData} />
          </div>
          <div style={{ height: '30%', minHeight: '200px', borderTop: '1px solid var(--hairline)' }}>
            <TerminalPanel projectId={activeRunId} />
          </div>
        </div>

        {/* Right pane — chat panel */}
        <div className="ide-pane-right">
          <ChatPanel
            runState={runState}
            isRunning={isRunning}
            onSubmit={handleSubmit}
            onApprove={handleApprove}
            onCancel={handleCancel}
            activeAgent={activeAgent}
          />
        </div>
      </div>

      {/* STOP button — fixed bottom-right while running or awaiting approval */}
      {showStopButton && (
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
