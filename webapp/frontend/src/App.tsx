import { useState, useEffect, useRef, useCallback } from 'react'
import './index.css'
import './App.css'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Step {
  agent: string
  status: 'done' | 'failed' | 'cancelled' | 'running'
  attempt_number: number
  input_summary: string
  output_summary: string
  verdict: string | null
  severity_counts: Record<string, number>
  duration_ms: number | null
  data: Record<string, unknown>
}

interface RunState {
  request_id: string
  feature_request: string
  started_at: string
  completed_at: string | null
  status: 'running' | 'success' | 'error' | 'cancelled'
  total_duration_ms: number | null
  steps: Step[]
}

interface LogEntry {
  filename: string
  request_id: string
  feature_request: string
  overall_status: string
  total_duration_ms: number | null
  started_at: string
  completed_at: string | null
  retry_count: number
}

interface MetricsData {
  total_runs: number
  success_rate: string
  retry_rate: string
  p50_ms: number | null
  max_ms: number | null
  last_updated: string | null
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BASE = 'http://localhost:8020'

const AGENTS = [
  { id: 'planner-agent', label: 'Planner' },
  { id: 'rag-agent', label: 'RAG' },
  { id: 'codegen-agent', label: 'Code-Gen' },
  { id: 'reviewer-agent', label: 'Reviewer' },
  { id: 'db-agent', label: 'DB Agent' },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtDuration(ms: number | null): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString()
}

function verdictClass(verdict: string | null, status: string): string {
  if (status === 'cancelled') return 'verdict-cancelled'
  if (status === 'failed') return 'verdict-failed'
  if (verdict === 'pass') return 'verdict-pass'
  if (verdict === 'fail') return 'verdict-fail'
  if (verdict === 'exhausted') return 'verdict-exhausted'
  return ''
}

function computeMetrics(logs: LogEntry[]): MetricsData {
  const total = logs.length
  if (total === 0) return { total_runs: 0, success_rate: '—', retry_rate: '—', p50_ms: null, max_ms: null, last_updated: null }
  const successes = logs.filter(l => l.overall_status === 'success').length
  const retried = logs.filter(l => l.retry_count > 0).length
  const durations = logs.map(l => l.total_duration_ms).filter((d): d is number => d != null).sort((a, b) => a - b)
  const p50 = durations.length ? durations[Math.floor(durations.length / 2)] : null
  const max = durations.length ? durations[durations.length - 1] : null
  const last = logs.reduce((a, b) => (a.completed_at ?? '') > (b.completed_at ?? '') ? a : b, logs[0])
  return {
    total_runs: total,
    success_rate: `${Math.round((successes / total) * 100)}%`,
    retry_rate: `${Math.round((retried / total) * 100)}%`,
    p50_ms: p50,
    max_ms: max,
    last_updated: last.completed_at,
  }
}

// ---------------------------------------------------------------------------
// Pipeline diagram SVG
// ---------------------------------------------------------------------------

function PipelineDiagram({ activeAgent }: { activeAgent: string | null }) {
  const nodes = AGENTS
  const W = 760
  const nodeW = 110
  const nodeH = 44
  const y = 60
  const gap = (W - nodeW * nodes.length) / (nodes.length - 1)

  return (
    <svg
      viewBox={`0 0 ${W} 120`}
      width="100%"
      style={{ display: 'block', maxWidth: 760, margin: '0 auto' }}
      aria-label="Pipeline diagram"
    >
      {/* Connector lines */}
      {nodes.slice(0, -1).map((n, i) => {
        const x1 = i * (nodeW + gap) + nodeW
        const x2 = (i + 1) * (nodeW + gap)
        const mid = (x1 + x2) / 2
        const isActive = activeAgent === n.id || activeAgent === nodes[i + 1].id
        return (
          <line
            key={n.id}
            x1={x1} y1={y + nodeH / 2}
            x2={x2} y2={y + nodeH / 2}
            stroke={isActive ? '#1c69d4' : '#3c3c3c'}
            strokeWidth={isActive ? 2 : 1}
          />
        )
      })}

      {/* Nodes */}
      {nodes.map((n, i) => {
        const x = i * (nodeW + gap)
        const isActive = activeAgent === n.id
        const accentH = 4
        return (
          <g key={n.id}>
            {/* Card background */}
            <rect
              x={x} y={y}
              width={nodeW} height={nodeH}
              fill={isActive ? '#1a1a1a' : '#0d0d0d'}
              stroke={isActive ? '#1c69d4' : '#3c3c3c'}
              strokeWidth={isActive ? 1.5 : 1}
            />
            {/* Active accent stripe (tricolor: blue-light → blue-dark → red) */}
            {isActive && (
              <>
                <rect x={x} y={y} width={Math.floor(nodeW / 3)} height={accentH} fill="#0066b1" />
                <rect x={x + Math.floor(nodeW / 3)} y={y} width={Math.floor(nodeW / 3)} height={accentH} fill="#1c69d4" />
                <rect x={x + Math.floor(nodeW / 3) * 2} y={y} width={nodeW - Math.floor(nodeW / 3) * 2} height={accentH} fill="#e22718" />
              </>
            )}
            {/* Label */}
            <text
              x={x + nodeW / 2} y={y + nodeH / 2 + 5}
              textAnchor="middle"
              fontSize={11}
              fontFamily="Inter, system-ui, sans-serif"
              fontWeight={700}
              letterSpacing={1}
              textDecoration="none"
              fill={isActive ? '#ffffff' : '#7e7e7e'}
              style={{ textTransform: 'uppercase' }}
            >
              {n.label}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Step card
// ---------------------------------------------------------------------------

function StepCard({ step, isRetry }: { step: Step; isRetry: boolean }) {
  const [open, setOpen] = useState(false)
  const agentLabel = AGENTS.find(a => a.id === step.agent)?.label ?? step.agent

  return (
    <div className={`step-card ${isRetry ? 'step-retry' : ''}`} data-status={step.status}>
      {isRetry && <div className="retry-label">RETRY — ATTEMPT {step.attempt_number}</div>}
      <div className="step-header" onClick={() => setOpen(o => !o)} style={{ cursor: 'pointer' }}>
        <div className="step-meta">
          <span className="step-agent">{agentLabel}</span>
          {step.verdict && (
            <span className={`step-verdict ${verdictClass(step.verdict, step.status)}`}>
              {step.verdict.toUpperCase()}
            </span>
          )}
          {step.status === 'failed' && <span className="step-verdict verdict-failed">FAILED</span>}
          {step.status === 'cancelled' && <span className="step-verdict verdict-cancelled">CANCELLED</span>}
        </div>
        <div className="step-right">
          {step.duration_ms != null && (
            <span className="step-dur">{fmtDuration(step.duration_ms)}</span>
          )}
          <span className="step-toggle">{open ? '▴' : '▾'}</span>
        </div>
      </div>

      {/* Output summary always visible */}
      {step.output_summary && (
        <div className="step-summary">{step.output_summary}</div>
      )}

      {/* Full data expandable */}
      {open && (
        <div className="step-detail">
          {/* RAG: show retrieved snippets + confidence */}
          {step.agent === 'rag-agent' && step.data && (
            <RagDetail data={step.data} />
          )}
          {/* Reviewer: show issue list grouped by severity */}
          {step.agent === 'reviewer-agent' && step.data && (
            <ReviewerDetail data={step.data} />
          )}
          {/* CodeGen: show generated code */}
          {step.agent === 'codegen-agent' && step.data && (
            <CodeGenDetail data={step.data} />
          )}
          {/* Planner: show subtask list */}
          {step.agent === 'planner-agent' && step.data && (
            <PlannerDetail data={step.data} />
          )}
          {/* DB: show SQL */}
          {(step.agent === 'db-agent' || step.agent === 'db-executor') && step.data && (
            <DbDetail data={step.data} />
          )}
          {/* Fallback: raw JSON */}
          {!['rag-agent', 'reviewer-agent', 'codegen-agent', 'planner-agent', 'db-agent', 'db-executor'].includes(step.agent) && (
            <pre className="detail-pre">{JSON.stringify(step.data, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  )
}

function RagDetail({ data }: { data: Record<string, unknown> }) {
  const answer = data.answer as string | undefined
  const confidence = data.confidence as number | undefined
  const lowConf = data.low_confidence as boolean | undefined
  const sources = data.sources as string[] | undefined
  return (
    <div className="detail-rag">
      {lowConf && <div className="low-conf-flag">⚠ LOW CONFIDENCE — treat this answer as unverified</div>}
      {confidence != null && (
        <div className="detail-row">
          <span className="detail-label">Confidence</span>
          <span className="detail-value">{(confidence * 100).toFixed(0)}%</span>
        </div>
      )}
      {answer && <div className="detail-answer">{answer}</div>}
      {sources && sources.length > 0 && (
        <div className="detail-sources">
          <div className="detail-label">Sources</div>
          {sources.map((s, i) => <div key={i} className="detail-source-item">{s}</div>)}
        </div>
      )}
    </div>
  )
}

function ReviewerDetail({ data }: { data: Record<string, unknown> }) {
  const issues = (data.issues as Array<{ severity: string; rule: string; message: string; line?: number }>) || []
  const byS: Record<string, typeof issues> = {}
  for (const iss of issues) {
    if (!byS[iss.severity]) byS[iss.severity] = []
    byS[iss.severity].push(iss)
  }
  const order = ['critical', 'error', 'warning', 'info']
  return (
    <div className="detail-reviewer">
      {issues.length === 0 && <div className="detail-empty">No issues found.</div>}
      {order.filter(s => byS[s]?.length).map(sev => (
        <div key={sev} className="issue-group">
          <div className={`issue-sev-header sev-${sev}`}>{sev.toUpperCase()} ({byS[sev].length})</div>
          {byS[sev].map((iss, i) => (
            <div key={i} className="issue-row">
              <span className="issue-rule">{iss.rule}</span>
              {iss.line != null && <span className="issue-line">L{iss.line}</span>}
              <span className="issue-msg">{iss.message}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function CodeGenDetail({ data }: { data: Record<string, unknown> }) {
  const artifact = data.artifact as Record<string, unknown> | undefined
  const code = artifact?.code as string | undefined
  const explanation = artifact?.explanation as string | undefined
  return (
    <div className="detail-codegen">
      {explanation && <div className="detail-explanation">{explanation}</div>}
      {code && <pre className="detail-code">{code}</pre>}
    </div>
  )
}

function PlannerDetail({ data }: { data: Record<string, unknown> }) {
  const subtasks = data.subtasks as Array<{ task_id: string; agent: string; description: string; dependencies: string[] }> | undefined
  return (
    <div className="detail-planner">
      {subtasks?.map(t => (
        <div key={t.task_id} className="planner-task">
          <span className="planner-tid">{t.task_id}</span>
          <span className="planner-agent">{t.agent}</span>
          <span className="planner-desc">{t.description}</span>
        </div>
      ))}
    </div>
  )
}

function DbDetail({ data }: { data: Record<string, unknown> }) {
  const query = data.query as string | undefined
  const desc = data.description as string | undefined
  return (
    <div className="detail-db">
      {desc && <div className="detail-db-desc">{desc}</div>}
      {query && <pre className="detail-code">{query}</pre>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Metrics strip
// ---------------------------------------------------------------------------

function MetricsStrip({ logs }: { logs: LogEntry[] }) {
  const m = computeMetrics(logs)
  const cells = [
    { value: String(m.total_runs), label: 'Total Runs' },
    { value: m.success_rate, label: 'Success Rate' },
    { value: m.retry_rate, label: 'Retry Rate' },
    { value: fmtDuration(m.p50_ms), label: 'P50 Duration' },
    { value: fmtDuration(m.max_ms), label: 'Max Duration' },
  ]
  return (
    <div className="metrics-strip">
      {cells.map(c => (
        <div key={c.label} className="metric-cell">
          <div className="metric-value">{c.value}</div>
          <div className="metric-label">{c.label}</div>
        </div>
      ))}
      {m.last_updated && (
        <div className="metric-cell metric-cell-note">
          <div className="metric-value" style={{ fontSize: 12 }}>from {logs.length} log{logs.length !== 1 ? 's' : ''}</div>
          <div className="metric-label">last run {fmtTime(m.last_updated)}</div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Run history list
// ---------------------------------------------------------------------------

type HistoryFilter = 'all' | 'success' | 'retried' | 'cancelled' | 'error'

function RunHistory({ logs }: { logs: LogEntry[] }) {
  const [filter, setFilter] = useState<HistoryFilter>('all')
  const tabs: { key: HistoryFilter; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'success', label: 'Passed' },
    { key: 'retried', label: 'Retried' },
    { key: 'cancelled', label: 'Cancelled' },
    { key: 'error', label: 'Failed' },
  ]
  const filtered = logs.filter(l => {
    if (filter === 'all') return true
    if (filter === 'retried') return l.retry_count > 0
    return l.overall_status === filter
  })

  return (
    <div className="history-section">
      <div className="section-accent-bar" />
      <h2 className="section-heading">Run History</h2>
      <div className="history-tabs">
        {tabs.map(t => (
          <button
            key={t.key}
            className={`history-tab ${filter === t.key ? 'active' : ''}`}
            onClick={() => setFilter(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="history-list">
        {filtered.length === 0 && (
          <div className="empty-state">No runs match this filter.</div>
        )}
        {filtered.slice().reverse().map(l => (
          <div key={l.request_id} className="history-card" data-status={l.overall_status}>
            <div className="hc-top">
              <span className={`hc-status status-${l.overall_status}`}>{l.overall_status?.toUpperCase()}</span>
              {l.retry_count > 0 && <span className="hc-retry">+{l.retry_count} retry</span>}
              <span className="hc-dur">{fmtDuration(l.total_duration_ms)}</span>
              <span className="hc-time">{fmtTime(l.completed_at)}</span>
            </div>
            <div className="hc-request">{l.feature_request || l.request_id}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------

export default function App() {
  const [request, setRequest] = useState('')
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [runState, setRunState] = useState<RunState | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [connected, setConnected] = useState(false)
  const [stopping, setStopping] = useState(false)

  const ws = useRef<WebSocket | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const traceEndRef = useRef<HTMLDivElement>(null)

  // WebSocket for legacy broadcast messages (file_update etc.)
  useEffect(() => {
    const connect = () => {
      ws.current = new WebSocket(`ws://localhost:8020/ws`)
      ws.current.onopen = () => setConnected(true)
      ws.current.onclose = () => { setConnected(false); setTimeout(connect, 3000) }
      ws.current.onerror = () => ws.current?.close()
    }
    connect()
    return () => ws.current?.close()
  }, [])

  // Load history from logs endpoint
  const refreshLogs = useCallback(async () => {
    try {
      const res = await fetch(`${BASE}/logs`)
      if (res.ok) setLogs(await res.json())
    } catch { /* backend not up yet */ }
  }, [])

  useEffect(() => { refreshLogs() }, [refreshLogs])

  // Poll the active run status
  useEffect(() => {
    if (!activeRunId) return
    const poll = async () => {
      try {
        const res = await fetch(`${BASE}/runs/${activeRunId}/status`)
        if (!res.ok) return
        const state: RunState = await res.json()
        setRunState(state)
        if (state.status !== 'running') {
          if (pollRef.current) clearInterval(pollRef.current)
          pollRef.current = null
          refreshLogs()
        }
      } catch { /* ignore */ }
    }
    poll()
    pollRef.current = setInterval(poll, 1500)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [activeRunId, refreshLogs])

  // Auto-scroll trace
  useEffect(() => {
    traceEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [runState?.steps?.length])

  const isRunning = runState?.status === 'running'

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!request.trim()) return
    try {
      const res = await fetch(`${BASE}/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request: request.trim() }),
      })
      if (!res.ok) return
      const data = await res.json()
      setActiveRunId(data.request_id)
      setRunState(null)
      setStopping(false)
      setRequest('')
    } catch (e) {
      console.error('Failed to start run', e)
    }
  }

  const handleStop = async () => {
    if (!activeRunId || !isRunning || stopping) return
    setStopping(true)
    try {
      const res = await fetch(`${BASE}/runs/${activeRunId}/cancel`, { method: 'POST' })
      if (!res.ok) setStopping(false)
      // UI reflects cancellation when /status returns cancelled — not optimistically
    } catch {
      setStopping(false)
    }
  }

  // Determine which agent node is currently active in the diagram
  const activeAgent: string | null = (() => {
    if (!runState || runState.status !== 'running') return null
    const steps = runState.steps
    if (steps.length === 0) return 'planner-agent'
    const last = steps[steps.length - 1]
    if (last.status === 'done' || last.status === 'failed') {
      // Find next agent to be dispatched — use planner output subtask list
      const plannerStep = steps.find(s => s.agent === 'planner-agent')
      const subtasks = (plannerStep?.data?.subtasks as Array<{ agent: string }>) ?? []
      const doneAgents = new Set(steps.map(s => s.agent))
      const next = subtasks.find(st => !doneAgents.has(st.agent))
      return next?.agent ?? null
    }
    return last.agent
  })()

  // Group steps for threaded retry display
  function groupedSteps(steps: Step[]) {
    // Pair codegen+reviewer steps by attempt_number
    const groups: { steps: Step[]; isRetry: boolean }[] = []
    let i = 0
    while (i < steps.length) {
      const s = steps[i]
      if (s.agent === 'codegen-agent') {
        const reviewerNext = steps[i + 1]?.agent === 'reviewer-agent' ? steps[i + 1] : undefined
        const isRetry = s.attempt_number > 1
        groups.push({ steps: reviewerNext ? [s, reviewerNext] : [s], isRetry })
        i += reviewerNext ? 2 : 1
      } else {
        groups.push({ steps: [s], isRetry: false })
        i++
      }
    }
    return groups
  }

  return (
    <div className="app">
      {/* ── Header ── */}
      <header className="app-header">
        <div className="header-inner">
          <div className="header-brand">
            <div className="brand-accent" />
            <span className="brand-name">Multi-Agent Pipeline</span>
          </div>
          <div className={`conn-pill ${connected ? 'conn-on' : 'conn-off'}`}>
            <span className="conn-dot" />
            {connected ? 'Connected' : 'Disconnected'}
          </div>
        </div>
      </header>

      <main className="app-main">

        {/* ── Composer ── */}
        <section className="composer-section">
          <form className="composer-form" onSubmit={handleSubmit}>
            <input
              className="composer-input"
              type="text"
              placeholder="Describe a feature request…"
              value={request}
              onChange={e => setRequest(e.target.value)}
              disabled={isRunning}
            />
            <button
              className="btn-primary"
              type="submit"
              disabled={!request.trim() || isRunning}
            >
              Run Pipeline
            </button>
          </form>
        </section>

        {/* ── Pipeline Diagram ── */}
        <section className="diagram-section">
          <div className="section-accent-bar" />
          <div className="diagram-inner">
            <PipelineDiagram activeAgent={activeAgent} />
          </div>
        </section>

        {/* ── Live Trace ── */}
        {runState && (
          <section className="trace-section">
            <div className="section-accent-bar" />
            <div className="trace-header">
              <h2 className="section-heading">
                Live Trace
                <span className={`run-status-badge status-${runState.status}`}>
                  {runState.status.toUpperCase()}
                </span>
              </h2>
              <div className="trace-meta">
                <span>{fmtTime(runState.started_at)}</span>
                {runState.total_duration_ms != null && (
                  <span>{fmtDuration(runState.total_duration_ms)} total</span>
                )}
              </div>
            </div>
            <div className="trace-request">"{runState.feature_request}"</div>

            <div className="trace-list">
              {runState.steps.length === 0 && isRunning && (
                <div className="trace-pending">Waiting for first agent response…</div>
              )}
              {groupedSteps(runState.steps).map((group, gi) => (
                <div key={gi} className={`trace-group ${group.isRetry ? 'trace-group-retry' : ''}`}>
                  {group.steps.map((step, si) => (
                    <StepCard
                      key={`${step.agent}-${step.attempt_number}-${si}`}
                      step={step}
                      isRetry={group.isRetry && step.agent === 'codegen-agent'}
                    />
                  ))}
                </div>
              ))}
              <div ref={traceEndRef} />
            </div>
          </section>
        )}

        {/* ── Metrics ── */}
        {logs.length > 0 && (
          <section className="metrics-section">
            <div className="section-accent-bar" />
            <h2 className="section-heading">Metrics</h2>
            <MetricsStrip logs={logs} />
          </section>
        )}

        {/* ── History ── */}
        {logs.length > 0 && <RunHistory logs={logs} />}

      </main>

      {/* ── STOP button (only while running) ── */}
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
