import { useEffect, useState } from 'react'
import Prism from 'prismjs'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-typescript'
import 'prismjs/components/prism-jsx'
import 'prismjs/components/prism-tsx'
import 'prismjs/components/prism-css'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-markdown'
import 'prismjs/components/prism-sql'
import { getFileContent } from '../api'

interface CodeEditorProps {
  selectedPath: string | null
}

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

export default function CodeEditor({ selectedPath }: CodeEditorProps) {
  const [content, setContent] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!selectedPath) {
      setContent(null)
      setError(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setContent(null)
    setError(null)
    getFileContent(selectedPath)
      .then(text => {
        if (!cancelled) {
          setContent(text)
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

  if (!selectedPath) {
    return (
      <div className="editor-placeholder" style={{ height: '100%' }}>
        Select a file to view its contents
      </div>
    )
  }

  const filename = selectedPath.split('/').pop() ?? selectedPath
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
        <span className="editor-filename">{filename}</span>
        <span className="editor-lang">{label}</span>
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
        {!loading && !error && content != null && (
          <pre className="editor-code">
            <code
              className={`language-${lang}`}
              dangerouslySetInnerHTML={{ __html: highlighted }}
            />
          </pre>
        )}
      </div>
    </div>
  )
}
