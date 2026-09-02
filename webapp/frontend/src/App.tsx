import { useState, useEffect, useRef } from 'react'
import Prism from 'prismjs'
import 'prismjs/themes/prism-tomorrow.css'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-javascript'
import 'prismjs/components/prism-typescript'
import { MessageSquare, Code, Folder, ChevronRight, ChevronDown } from 'lucide-react'
import './App.css'

interface LogEntry {
  type: string;
  agent?: string;
  message?: string;
  status?: string;
  data?: any;
  request_id?: string;
  request?: string;
  id?: number;
}

interface FileNode {
  name: string;
  type: 'file' | 'folder';
  path: string;
  children?: FileNode[];
}

function App() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [request, setRequest] = useState("")
  const [files, setFiles] = useState<FileNode | null>(null)
  const [activeFileContent, setActiveFileContent] = useState<string>("")
  const [activeFileName, setActiveFileName] = useState<string>("")
  const [isConnected, setIsConnected] = useState(false)
  const [expandedLogs, setExpandedLogs] = useState<Set<number>>(new Set())
  
  const ws = useRef<WebSocket | null>(null)
  const logsEndRef = useRef<HTMLDivElement>(null)
  const logCounter = useRef(0)

  useEffect(() => {
    connectWs()
    fetchFiles()
    return () => {
      if (ws.current) ws.current.close()
    }
  }, [])

  useEffect(() => {
    if (activeFileContent) {
      setTimeout(() => Prism.highlightAll(), 0)
    }
  }, [activeFileContent])

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const connectWs = () => {
    ws.current = new WebSocket('ws://localhost:8020/ws')
    
    ws.current.onopen = () => setIsConnected(true)
    ws.current.onclose = () => setIsConnected(false)
    
    ws.current.onmessage = (event) => {
      const data: LogEntry = JSON.parse(event.data)
      if (data.type === 'file_update') {
        fetchFiles()
        // Automatically open the file that was updated
        if (data.path && data.filename) {
          loadFile(data.path, data.filename)
        }
      } else if (data.type === 'file_delete') {
         fetchFiles()
         // Clear code viewer if it was the file being viewed
         setActiveFileName((prev) => {
           if (prev === data.filename) {
             setActiveFileContent("")
             return ""
           }
           return prev
         })
      } else {
        data.id = logCounter.current++
        setLogs(prev => [...prev, data])
      }
    }
  }

  const fetchFiles = async () => {
    try {
      const res = await fetch('http://localhost:8020/files')
      const data = await res.json()
      setFiles(data)
    } catch (e) {
      console.error(e)
    }
  }

  const loadFile = async (path: string, name: string) => {
    try {
      const res = await fetch(`http://localhost:8020/file?path=${encodeURIComponent(path)}`)
      const data = await res.json()
      setActiveFileContent(data.content || '')
      setActiveFileName(name)
    } catch (e) {
      console.error(e)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!request.trim()) return

    try {
      await fetch('http://localhost:8020/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request })
      })
      setRequest("")
    } catch (e) {
      console.error(e)
    }
  }

  const toggleLogExpand = (id: number) => {
    setExpandedLogs(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const renderTree = (node: FileNode) => {
    if (node.type === 'folder') {
      return (
        <div key={node.path} className="tree-folder">
          <div className="tree-item folder-label">
            <Folder size={16} /> <span>{node.name}</span>
          </div>
          <div className="tree-children">
            {node.children?.map(renderTree)}
          </div>
        </div>
      )
    }
    return (
      <div 
        key={node.path} 
        className={`tree-item file-item ${activeFileName === node.name ? 'active' : ''}`}
        onClick={() => loadFile(node.path, node.name)}
      >
        <Code size={16} /> <span>{node.name}</span>
      </div>
    )
  }

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>Orchestrator IDE</h1>
        <div className={`status ${isConnected ? 'online' : 'offline'}`}>
          {isConnected ? 'Connected' : 'Disconnected'}
        </div>
      </header>
      
      <main className="app-main">
        {/* Left Panel: File Explorer */}
        <section className="panel file-explorer">
          <h2>Project Explorer</h2>
          <div className="tree-view">
            {files ? renderTree(files) : <div className="empty-state">Loading files...</div>}
          </div>
        </section>

        {/* Center Panel: Code Viewer */}
        <section className="panel code-viewer">
          <h2>{activeFileName || "No File Opened"}</h2>
          <div className="editor-area">
            {activeFileContent ? (
              <pre><code className={`language-${activeFileName.split('.').pop() || 'none'}`}>{activeFileContent}</code></pre>
            ) : (
              <div className="empty-state">Select a file from the explorer to view its contents</div>
            )}
          </div>
        </section>

        {/* Right Panel: Chat & Feed */}
        <section className="panel side-panel">
          <div className="reasoning-feed">
            <h2>Activity Feed</h2>
            <div className="logs-container">
              {logs.map((log) => {
                if (log.type === 'start') {
                  return (
                    <div key={log.id} className="log-entry log-header">
                      Started Request: {log.request}
                    </div>
                  )
                }
                if (log.type === 'done') {
                  return (
                    <div key={log.id} className="log-entry log-header success">
                      Completed Request
                    </div>
                  )
                }
                if (log.type === 'log') {
                  const isExpanded = expandedLogs.has(log.id!)
                  const hasDetails = log.data != null
                  
                  return (
                    <div key={log.id} className={`log-entry ${log.status || 'active'}`}>
                      <div className="log-indicator"></div>
                      <div 
                        className={`log-content ${!isExpanded ? 'collapsed' : ''}`}
                        onClick={() => hasDetails && toggleLogExpand(log.id!)}
                      >
                        <div className="log-top-row">
                          {hasDetails && (
                            isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />
                          )}
                          <span className="agent-badge">{log.agent}</span>
                          <span className="log-message">{log.message}</span>
                        </div>
                        {hasDetails && (
                          <div className="log-details">
                            {typeof log.data === 'string' ? log.data : JSON.stringify(log.data, null, 2)}
                          </div>
                        )}
                      </div>
                    </div>
                  )
                }
                return null
              })}
              <div ref={logsEndRef} />
            </div>
          </div>

          <div className="chat-window">
            <form onSubmit={handleSubmit} className="chat-form">
              <input 
                type="text" 
                value={request}
                onChange={(e) => setRequest(e.target.value)}
                placeholder="Describe a full project outcome..."
                className="chat-input"
              />
              <button type="submit" className="chat-submit" disabled={!request.trim() || !isConnected}>
                <MessageSquare size={18} />
              </button>
            </form>
          </div>
        </section>
      </main>
    </div>
  )
}

export default App
