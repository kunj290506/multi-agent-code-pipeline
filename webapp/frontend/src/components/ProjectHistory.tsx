import { useEffect, useState } from 'react'
import type { Project } from '../types'
import { getProjects } from '../api'

interface ProjectHistoryProps {
  activeProjectId: string | null
  onSelectProject: (projectId: string) => void
}

export default function ProjectHistory({ activeProjectId, onSelectProject }: ProjectHistoryProps) {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getProjects()
      .then(data => {
        if (!cancelled) {
          setProjects(data)
          setLoading(false)
        }
      })
      .catch(err => {
        if (!cancelled) {
          console.error('Failed to load projects', err)
          setLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [])

  const fmtDate = (ts: number) => {
    if (!ts) return 'Unknown date'
    const d = new Date(ts * 1000)
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  }

  return (
    <div className="project-history">
      <div className="history-header">
        <span className="history-title">PROJECT HISTORY</span>
      </div>
      
      {loading ? (
        <div className="history-empty">Loading projects…</div>
      ) : projects.length === 0 ? (
        <div className="history-empty">No projects found.</div>
      ) : (
        <div className="history-list">
          {projects.map(p => (
            <div
              key={p.request_id}
              className={`history-item ${activeProjectId === p.request_id ? 'history-item-active' : ''}`}
              onClick={() => onSelectProject(p.request_id)}
            >
              <div className="history-item-top">
                <span className="history-item-name">{p.project_name}</span>
                <span className={`history-item-status status-${p.status}`}>
                  {p.status.toUpperCase()}
                </span>
              </div>
              <div className="history-item-desc" title={p.feature_request}>
                {p.feature_request}
              </div>
              <div className="history-item-meta">
                <span>{fmtDate(p.timestamp)}</span>
                <span>{p.file_count} files</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
