import { useEffect, useRef, useState } from 'react'
import type { RunState, Step, Subtask } from '../types'
import Magnetic from './Magnetic'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
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

// Group steps for threaded retry display
function groupedSteps(steps: Step[]) {
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

// ---------------------------------------------------------------------------
// Pipeline Diagram SVG
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
          <g key={n.id} className={isActive ? 'diagram-node-active' : ''}>
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
// Plan Approval Component
// ---------------------------------------------------------------------------
function PlanApproval({
  plan,
  onApprove,
  onCancel,
}: {
  plan: { subtasks: Subtask[]; reasoning?: string }
  onApprove: (subtasks: Subtask[]) => void
  onCancel: () => void
}) {
  const [subtasks, setSubtasks] = useState<Subtask[]>(plan.subtasks)
  const [reasoningOpen, setReasoningOpen] = useState(false)
  const [approving, setApproving] = useState(false)

  const removeStep = (taskId: string) => {
    setSubtasks(prev => prev.filter(s => s.task_id !== taskId))
  }

  const setStrategy = (taskId: string, strategy: any) => {
    setSubtasks(prev => prev.map(s => s.task_id === taskId ? { ...s, resolution_strategy: strategy } : s))
  }

  const hasBlocked = subtasks.some(s => s.preflight_status === 'blocked')

  const handleApprove = () => {
    if (subtasks.length === 0) return
    setApproving(true)
    onApprove(subtasks)
  }

  const agentLabel = (agentId: string) =>
    AGENTS.find(a => a.id === agentId)?.label ?? agentId

  return (
    <div className="plan-approval">
      <div className="plan-approval-header">
        <div className="plan-approval-title">PLAN READY — {subtasks.length} STEP{subtasks.length !== 1 ? 'S' : ''}</div>
      </div>

      {/* Reasoning block */}
      {plan.reasoning && (
        <div className="step-reasoning">
          <div
            className="step-reasoning-header"
            onClick={() => setReasoningOpen(o => !o)}
          >
            <span>REASONING</span>
            <span>{reasoningOpen ? '▾' : '▸'}</span>
          </div>
          {reasoningOpen && (
            <div className="step-reasoning-body">{plan.reasoning}</div>
          )}
        </div>
      )}

      {/* Subtask list */}
      <div className="plan-steps">
        {subtasks.map((task, idx) => (
          <div key={task.task_id} className="plan-step">
            <div className="plan-step-num">{idx + 1}</div>
            <div className="plan-step-body">
              <div className="plan-step-meta">
                <span className="plan-step-agent">{agentLabel(task.agent)}</span>
                {task.target_filename && (
                  <span className="plan-step-file">{task.target_filename}</span>
                )}
              </div>
              <div className="plan-step-desc">{task.description}</div>
              {task.preflight_status && task.preflight_status !== 'ok' && (
                <div className={`preflight-alert preflight-${task.preflight_status}`}>
                  <div className="preflight-alert-text">⚠ {task.preflight_details}</div>
                  {task.preflight_old_content !== undefined && (
                    <div className="preflight-resolution">
                      <label>Action:</label>
                      <select 
                        value={task.resolution_strategy || 'overwrite'}
                        onChange={(e) => setStrategy(task.task_id, e.target.value)}
                      >
                        <option value="overwrite">Overwrite</option>
                        <option value="rename">Rename</option>
                        <option value="skip">Skip</option>
                      </select>
                      <details className="preflight-preview">
                        <summary>Preview Existing File</summary>
                        <pre>{task.preflight_old_content}</pre>
                      </details>
                    </div>
                  )}
                </div>
              )}
            </div>
            <button
              className="plan-step-remove"
              onClick={() => removeStep(task.task_id)}
              title="Remove this step"
              aria-label={`Remove step ${task.task_id}`}
            >
              ✕
            </button>
          </div>
        ))}
        {subtasks.length === 0 && (
          <div className="plan-steps-empty">All steps removed. Add steps back or cancel.</div>
        )}
      </div>

      {/* Action buttons */}
      <div className="plan-actions">
        <Magnetic>
          <button
            className="btn-primary plan-run-btn"
            onClick={handleApprove}
            disabled={subtasks.length === 0 || approving || hasBlocked}
          >
            {approving ? 'APPROVING…' : hasBlocked ? 'BLOCKED' : 'RUN PLAN'}
          </button>
        </Magnetic>
        <Magnetic>
          <button
            className="plan-cancel-btn"
            onClick={onCancel}
            disabled={approving}
          >
            CANCEL
          </button>
        </Magnetic>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Detail sub-components
// ---------------------------------------------------------------------------
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
// Step card (with reasoning block)
// ---------------------------------------------------------------------------
function StepCard({ step, isRetry }: { step: Step; isRetry: boolean }) {
  const [open, setOpen] = useState(false)
  const [reasoningOpen, setReasoningOpen] = useState(false)
  const agentLabel = AGENTS.find(a => a.id === step.agent)?.label ?? step.agent
  const reasoning = typeof step.data?.reasoning === 'string' && step.data.reasoning.trim()
    ? (step.data.reasoning as string)
    : null

  return (
    <div className={`step-card step-card-enter ${isRetry ? 'step-retry' : ''}`} data-status={step.status}>
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
          <span className="step-toggle">{open ? '▾' : '▸'}</span>
        </div>
      </div>
      {/* Output summary always visible */}
      {step.output_summary && (
        <div className="step-summary">{step.output_summary}</div>
      )}
      {/* Reasoning block — collapsible, above detail block */}
      {reasoning && (
        <div className="step-reasoning">
          <div
            className="step-reasoning-header"
            onClick={() => setReasoningOpen(o => !o)}
          >
            <span>REASONING</span>
            <span>{reasoningOpen ? '▾' : '▸'}</span>
          </div>
          {reasoningOpen && (
            <div className="step-reasoning-body">{reasoning}</div>
          )}
        </div>
      )}
      {/* Full data expandable */}
      {open && (
        <div className="step-detail">
          {step.agent === 'rag-agent' && step.data && (
            <RagDetail data={step.data} />
          )}
          {step.agent === 'reviewer-agent' && step.data && (
            <ReviewerDetail data={step.data} />
          )}
          {step.agent === 'codegen-agent' && step.data && (
            <CodeGenDetail data={step.data} />
          )}
          {step.agent === 'planner-agent' && step.data && (
            <PlannerDetail data={step.data} />
          )}
          {(step.agent === 'db-agent' || step.agent === 'db-executor') && step.data && (
            <DbDetail data={step.data} />
          )}
          {!['rag-agent', 'reviewer-agent', 'codegen-agent', 'planner-agent', 'db-agent', 'db-executor'].includes(step.agent) && (
            <pre className="detail-pre">{JSON.stringify(step.data, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Chat Panel props
// ---------------------------------------------------------------------------
interface ChatPanelProps {
  runState: RunState | null
  isRunning: boolean
  onSubmit: (request: string, projectName: string) => Promise<void>
  onApprove: (subtasks: Subtask[]) => Promise<void>
  onCancel: () => void
  activeAgent: string | null
}

// ---------------------------------------------------------------------------
// Chat Panel
// ---------------------------------------------------------------------------
export default function ChatPanel({ runState, isRunning, onSubmit, onApprove, onCancel, activeAgent }: ChatPanelProps) {
  const [prompt, setPrompt] = useState('')
  const [projectName, setProjectName] = useState('')
  const traceEndRef = useRef<HTMLDivElement>(null)

  const isAwaitingApproval = runState?.status === 'awaiting_approval'
  const inputDisabled = isRunning || isAwaitingApproval

  // Auto-scroll when new steps arrive
  useEffect(() => {
    traceEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [runState?.steps?.length, runState?.status])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!prompt.trim() || inputDisabled) return
    await onSubmit(prompt.trim(), projectName.trim())
    setPrompt('')
    setProjectName('')
  }

  return (
    <div className="chat-panel">
      {/* Pipeline diagram */}
      <div className="chat-diagram">
        <PipelineDiagram activeAgent={activeAgent} />
      </div>

      {/* Scrollable trace area */}
      <div className="chat-trace">
        {!runState && (
          <div className="chat-trace-empty">Enter a prompt below to start.</div>
        )}
        {runState && runState.steps.length === 0 && isRunning && (
          <div className="chat-trace-empty">Waiting for first agent response…</div>
        )}
        {runState && runState.steps.length > 0 && (
          <>
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
          </>
        )}

        {/* Plan Approval UI — shown when status is awaiting_approval */}
        {isAwaitingApproval && runState?.plan && (
          <PlanApproval
            plan={runState.plan}
            onApprove={onApprove}
            onCancel={onCancel}
          />
        )}

        <div ref={traceEndRef} />
      </div>

      {/* Prompt form */}
      <form className="chat-form" onSubmit={handleSubmit}>
        <div className="chat-input-wrapper">
          <textarea
            className="chat-textarea"
            placeholder="Describe what to build…"
            rows={3}
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSubmit(e as unknown as React.FormEvent)
              }
            }}
            disabled={inputDisabled}
          />
          {inputDisabled ? (
            <button
              type="button"
              className="chat-action-btn chat-stop-btn"
              onClick={onCancel}
              aria-label="Stop"
            >
              <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
            </button>
          ) : (
            <button
              type="submit"
              className="chat-action-btn chat-send-btn"
              disabled={!prompt.trim()}
              aria-label="Run Pipeline"
            >
              <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
              </svg>
            </button>
          )}
        </div>
        <input
          className="chat-project-input"
          type="text"
          placeholder="Project name (optional — leave blank to add to existing project)"
          value={projectName}
          onChange={e => setProjectName(e.target.value)}
          disabled={inputDisabled}
        />
        {runState && (
          <div className="chat-run-status">
            <span className={`run-status-badge status-${runState.status}`}>
              {runState.status === 'awaiting_approval' ? 'AWAITING APPROVAL' : runState.status.toUpperCase()}
            </span>
            <span>{fmtTime(runState.started_at)}</span>
            {runState.total_duration_ms != null && (
              <span>{fmtDuration(runState.total_duration_ms)} total</span>
            )}
          </div>
        )}
      </form>
    </div>
  )
}
