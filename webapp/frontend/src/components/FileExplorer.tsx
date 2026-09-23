import { useEffect, useState } from 'react'
import { getFiles } from '../api'
import type { FileNode } from '../types'

interface FileExplorerProps {
  selectedPath: string | null
  onSelect: (path: string) => void
  onDoubleClick?: (path: string) => void
  refreshTrigger: number
  /** When set, the explorer shows the workspace for this run ID instead of the default target-app/. */
  projectId?: string
}

function TreeNode({
  node,
  depth,
  selectedPath,
  onSelect,
  onDoubleClick,
}: {
  node: FileNode
  depth: number
  selectedPath: string | null
  onSelect: (path: string) => void
  onDoubleClick?: (path: string) => void
}) {
  const [expanded, setExpanded] = useState(true)
  const paddingLeft = 12 + depth * 12

  if (node.type === 'folder') {
    return (
      <div>
        <div
          className="explorer-row folder"
          style={{ paddingLeft }}
          onClick={() => setExpanded(e => !e)}
        >
          <span style={{ marginRight: 4 }}>{expanded ? '' : ''}</span>
          <span className="explorer-row-name">{node.name}</span>
        </div>
        {expanded && node.children?.map(child => (
          <TreeNode
            key={child.path}
            node={child}
            depth={depth + 1}
            selectedPath={selectedPath}
            onSelect={onSelect}
            onDoubleClick={onDoubleClick}
          />
        ))}
      </div>
    )
  }

  const isSelected = node.path === selectedPath
  return (
    <div
      className={`explorer-row${isSelected ? ' selected' : ''}`}
      style={{ paddingLeft }}
      onClick={() => onSelect(node.path)}
      onDoubleClick={() => onDoubleClick && onDoubleClick(node.path)}
    >
      <span className="explorer-row-name">{node.name}</span>
    </div>
  )
}

export default function FileExplorer({ selectedPath, onSelect, onDoubleClick, refreshTrigger, projectId }: FileExplorerProps) {
  const [root, setRoot] = useState<FileNode | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getFiles(projectId)
      .then(data => {
        if (!cancelled) {
          setRoot(data)
          setLoading(false)
        }
      })
      .catch(err => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load files')
          setLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [refreshTrigger, projectId])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div className="explorer-header">Explorer</div>
      <div className="explorer-tree">
        {loading && (
          <div className="explorer-empty">Loading…</div>
        )}
        {error && (
          <div className="explorer-empty" style={{ color: '#e22718' }}>{error}</div>
        )}
        {!loading && !error && root && (
          root.children && root.children.length > 0
            ? root.children.map(child => (
                <TreeNode
                  key={child.path}
                  node={child}
                  depth={0}
                  selectedPath={selectedPath}
                  onSelect={onSelect}
                  onDoubleClick={onDoubleClick}
                />
              ))
            : <div className="explorer-empty">No files generated yet.</div>
        )}
        {!loading && !error && !root && (
          <div className="explorer-empty">No files generated yet.</div>
        )}
      </div>
    </div>
  )
}
