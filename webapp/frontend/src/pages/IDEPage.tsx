import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { startRun, cancelRun, getRunStatus, runProject, approvePlan } from '../api'
import type { RunState, Subtask } from '../types'
import FileExplorer from '../components/FileExplorer'
import CodeEditor from '../components/CodeEditor'
import ChatPanel from '../components/ChatPanel'
import TerminalPanel from '../components/TerminalPanel'

export default function IDEPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const [openFiles, setOpenFiles] = useState<string[]>([])
  const [activeFile, setActiveFile] = useState<string | null>(null)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [terminalProjectId, setTerminalProjectId] = useState<string | null>(null)
  const [runState, setRunState] = useState<RunState | null>(null)
  const [connected, setConnected] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [explorerRefresh, setExplorerRefresh] = useState(0)
  const [diffData, setDiffData] = useState<{ filename: string; previous_content: string | null; new_content: string } | null>(null)

  const ws = useRef<WebSocket | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    setOpenFiles([])
    setActiveFile(null)
    setActiveRunId(null)
    setTerminalProjectId(null)
    setRunState(null)
    setDiffData(null)
    setExplorerRefresh(n => n + 1)
  }, [user?.id])

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
            const projectId = msg.request_id
            runProject(projectId).then(result => {
              if (result.runnable && result.url) {
                setTerminalProjectId(projectId)
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
  }, [activeRunId])

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
      setTerminalProjectId(null)
      setRunState(null)
      setStopping(false)
      if (!isFollowUp) {
        setOpenFiles([])
        setActiveFile(null)
      }
      setExplorerRefresh(n => n + 1) // immediately refresh explorer
    } catch (err) {
      console.error('Failed to start run', err)
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
          {activeRunId && (
            <button 
              onClick={async () => {
                try {
                  const result = await runProject(activeRunId)
                  if (result.runnable && result.url) {
                    setTerminalProjectId(activeRunId)
                     window.open(result.url, '_blank', 'noopener,noreferrer')
                     alert(`Deployment Details\n\nURL: ${result.url}\n(Login details generated by LLM if applicable)`)
                  } else {
                     alert(`Failed to run: ${result.reason}`)
                  }
                } catch (err) {
                  alert('Error running project')
                }
              }}
              style={{ background: 'var(--accent)', color: 'white', border: 'none', padding: '4px 12px', borderRadius: '4px', cursor: 'pointer', marginRight: '16px', fontSize: '0.85rem' }}
            >
              ▶ Run Project
            </button>
          )}
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
        {/* Left pane — current workspace files */}
        <div className="ide-pane-left" style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, minHeight: 0 }}>
            <FileExplorer
              selectedPath={activeFile}
              onSelect={() => {}} // Single click just selects in tree natively, no-op here for IDEPage unless we want to track it
              onDoubleClick={(path) => {
                if (!openFiles.includes(path)) {
                  setOpenFiles(prev => [...prev, path])
                }
                setActiveFile(path)
              }}
              refreshTrigger={explorerRefresh}
              projectId={activeRunId ?? undefined}
            />
          </div>
        </div>

        {/* Center pane — code editor + terminal */}
        <div className="ide-pane-center" style={{ display: 'flex', flexDirection: 'column', position: 'relative' }}>
          {!activeRunId && !activeFile && (
            <div style={{ position: 'absolute', inset: 0, zIndex: 10, background: 'var(--bg-pane)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--fg-muted)', textAlign: 'center', padding: '2rem' }}>
              <p style={{ fontSize: '1rem' }}>Type a prompt on the right (e.g. "make a calculator") to generate a new app.</p>
            </div>
          )}
          <div style={{ flex: 1, minHeight: 0 }}>
            <CodeEditor 
              activeFile={activeFile} 
              openFiles={openFiles} 
              onSelectTab={setActiveFile} 
              onCloseTab={(path) => {
                const newFiles = openFiles.filter(f => f !== path)
                setOpenFiles(newFiles)
                if (activeFile === path) {
                  setActiveFile(newFiles.length > 0 ? newFiles[newFiles.length - 1] : null)
                }
              }}
              diffData={diffData} 
            />
          </div>
          <div style={{ height: '30%', minHeight: '200px', borderTop: '1px solid var(--hairline)' }}>
            <TerminalPanel projectId={terminalProjectId} enabled={terminalProjectId === activeRunId} />
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

      {/* STOP button moved to ChatPanel */}
    </div>
  )
}
