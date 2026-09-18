import { useEffect, useState, useCallback } from 'react'
import Prism from 'prismjs'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-typescript'
import 'prismjs/components/prism-jsx'
import 'prismjs/components/prism-tsx'
import 'prismjs/components/prism-css'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-markdown'
import 'prismjs/components/prism-sql'
import { getFileContent, saveFile } from '../api'
import { computeUnifiedDiff, type DiffLine } from '../utils/diff'

interface CodeEditorProps {
  selectedPath: string | null
  /** file_written events from the pipeline (pushed via WebSocket/SSE) */
  diffData?: { filename: string; previous_content: string | null; new_content: string } | null
}

type EditorMode = 'editor' | 'diff'

function detectLanguage(path: string): { lang: string; label: string } {
  const ext = path.split('.').pop()?.toLowerCase() ?? ''
  switch (ext) {
    case 'py':    return { lang: 'python',     label: 'PYTHON' }
    case 'js':    return { lang: 'javascript', label: 'JAVASCRIPT' }
    case 'jsx':   return { lang: 'jsx',        label: 'JSX' }
    case 'ts':    return { lang: 'typescript', label: 'TYPESCRIPT' }
    case 'tsx':   return { lang: 'tsx',        label: 'TSX' }
    case 'html':  return { lang: 'markup',     label: 'HTML' }
    case 'css':   return { lang: 'css',        label: 'CSS' }
    case 'json':  return { lang: 'json',       label: 'JSON' }
    case 'md':    return { lang: 'markdown',   label: 'MARKDOWN' }
    case 'sql':   return { lang: 'sql',        label: 'SQL' }
    default:      return { lang: 'none',       label: ext.toUpperCase() || 'TEXT' }
  }
}

// ---------------------------------------------------------------------------
// Diff View sub-component
// ---------------------------------------------------------------------------
function DiffView({ lines }: { lines: DiffLine[] }) {
  if (lines.length === 0) {
    return <div className="editor-placeholder" style={{ height: '100%' }}>No changes to display.</div>
  }
  return (
    <pre className="diff-view">
      {lines.map((line, i) => (
        <div key={i} className={`diff-line diff-${line.type}`}>
          <span className="diff-line-no diff-line-old">
            {line.oldLineNo ?? ' '}
          </span>
          <span className="diff-line-no diff-line-new">
            {line.newLineNo ?? ' '}
          </span>
          <span className="diff-prefix">
            {line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' '}
          </span>
          <span className="diff-content">{line.content}</span>
        </div>
      ))}
    </pre>
  )
}

// ---------------------------------------------------------------------------
// Code Editor
// ---------------------------------------------------------------------------
export default function CodeEditor({ selectedPath, diffData }: CodeEditorProps) {
  const [content, setContent] = useState<string | null>(null)
  const [editedContent, setEditedContent] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState<string | null>(null)
  const [mode, setMode] = useState<EditorMode>('editor')
  const [diffLines, setDiffLines] = useState<DiffLine[]>([])

  const hasUnsavedChanges = editedContent !== null && editedContent !== content

  // Load file content
  useEffect(() => {
    if (!selectedPath) {
      setContent(null)
      setEditedContent(null)
      setError(null)
      setDiffLines([])
      return
    }
    let cancelled = false
    setLoading(true)
    setContent(null)
    setEditedContent(null)
    setError(null)
    setSaveMsg(null)
    getFileContent(selectedPath)
      .then(text => {
        if (!cancelled) {
          setContent(text)
          setEditedContent(text)
          setLoading(false)
        }
      })
      .catch(err => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load file')
          setLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [selectedPath])

  // When diffData arrives for the selected file, compute diff and switch to diff mode
  useEffect(() => {
    if (!diffData || !selectedPath) return
    // Match by filename (the last segment of selectedPath)
    const selectedFilename = selectedPath.split(/[\\/]/).pop()
    if (selectedFilename === diffData.filename) {
      const lines = computeUnifiedDiff(diffData.previous_content, diffData.new_content, diffData.filename)
      setDiffLines(lines)
      setMode('diff')
      // Also update content to the new version
      setContent(diffData.new_content)
      setEditedContent(diffData.new_content)
    }
  }, [diffData, selectedPath])

  const handleSave = useCallback(async () => {
    if (!selectedPath || editedContent === null || saving) return
    setSaving(true)
    setSaveMsg(null)
    try {
      await saveFile(selectedPath, editedContent)
      setContent(editedContent)
      setSaveMsg('Saved')
      setTimeout(() => setSaveMsg(null), 2000)
    } catch (err) {
      setSaveMsg(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }, [selectedPath, editedContent, saving])

  if (!selectedPath) {
    return (
      <div className="editor-placeholder" style={{ height: '100%' }}>
        Select a file to view its contents
      </div>
    )
  }

  const filename = selectedPath.split(/[\\/]/).pop() ?? selectedPath
  const { lang, label } = detectLanguage(selectedPath)

  const highlighted =
    content != null && lang !== 'none'
      ? Prism.highlight(content, Prism.languages[lang] ?? Prism.languages.plain, lang)
      : content != null
        ? content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        : ''

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div className="editor-header">
        <span className="editor-filename">
          {filename}
          {hasUnsavedChanges && <span className="editor-unsaved-dot" title="Unsaved changes">●</span>}
        </span>
        <span className="editor-lang">{label}</span>

        {/* Mode tabs */}
        <div className="editor-tabs">
          <button
            className={`editor-tab ${mode === 'editor' ? 'editor-tab-active' : ''}`}
            onClick={() => setMode('editor')}
          >
            EDITOR
          </button>
          <button
            className={`editor-tab ${mode === 'diff' ? 'editor-tab-active' : ''}`}
            onClick={() => setMode('diff')}
          >
            DIFF
          </button>
        </div>

        <div className="editor-header-right">
          {saveMsg && <span className="editor-save-msg">{saveMsg}</span>}
          {mode === 'editor' && (
            <button
              className="editor-save-btn"
              onClick={handleSave}
              disabled={!hasUnsavedChanges || saving}
            >
              {saving ? 'SAVING…' : 'SAVE'}
            </button>
          )}
        </div>
      </div>
      <div className="editor-content">
        {loading && (
          <div className="editor-placeholder" style={{ height: '100%' }}>
            Loading…
          </div>
        )}
        {error && (
          <div className="editor-placeholder" style={{ height: '100%', color: '#e22718' }}>
            {error}
          </div>
        )}
        {!loading && !error && mode === 'editor' && editedContent != null && (
          <textarea
            className="editor-textarea"
            value={editedContent}
            onChange={e => setEditedContent(e.target.value)}
            spellCheck={false}
          />
        )}
        {!loading && !error && mode === 'editor' && editedContent == null && content != null && (
          <pre className="editor-code">
            <code
              className={`language-${lang}`}
              dangerouslySetInnerHTML={{ __html: highlighted }}
            />
          </pre>
        )}
        {!loading && !error && mode === 'diff' && (
          <DiffView lines={diffLines} />
        )}
      </div>
    </div>
  )
}
