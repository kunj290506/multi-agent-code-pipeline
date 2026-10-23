// frontend/src/App.tsx - MultiAgent Code (Login Page, Clean File Explorer, Right-Side Chat, No Emojis)
import React, { useState, useEffect, useRef } from 'react';
import {
  fetchHealth,
  fetchModels,
  createSession,
  updateSession,
  stopSessionTurn,
  resolveApproval,
  fetchFileTree,
  readFile,
  saveFile,
  undoFile,
  fetchAuditLogs,
  streamAgentTurn,
  loginUser,
  clearAuthToken,
  getPreviewUrl,
} from './api';
import type {
  StepItem,
  HealthStatus,
  FileTreeNode,
} from './api';
import './index.css';

interface ChatMessage {
  id: string;
  sender: 'user' | 'agent';
  text: string;
  timestamp: number;
}

export default function App() {
  // Theme state: dark (original black/blue/red) vs light
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return (localStorage.getItem('multiagent_theme') as 'dark' | 'light') || 'dark';
  });

  // Authentication State
  const [currentUser, setCurrentUser] = useState<string | null>(() => {
    return localStorage.getItem('multiagent_user');
  });
  const [loginUsername, setLoginUsername] = useState<string>('');
  const [loginPassword, setLoginPassword] = useState<string>('');
  const [loginError, setLoginError] = useState<string>('');
  const [isLoggingIn, setIsLoggingIn] = useState<boolean>(false);

  // Services & Models
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [models, setModels] = useState<string[]>(['qwen2.5-coder:3b', 'qwen2.5:7b-instruct-q4_K_M']);
  const [activeSessionId, setActiveSessionId] = useState<string>('');
  const [selectedModel, setSelectedModel] = useState<string>('qwen2.5-coder:3b');
  const [autoApproveWrites, setAutoApproveWrites] = useState<boolean>(true);
  const [activeApproval, setActiveApproval] = useState<{ approval_id: string; tool: string; arguments: any; reason: string } | null>(null);

  // Right-Side Chat & Pipeline Execution State
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [steps, setSteps] = useState<StepItem[]>([]);
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [streamingToken, setStreamingToken] = useState<string>('');
  const [currentStage, setCurrentStage] = useState<'idle' | 'planner' | 'coder' | 'review' | 'executor' | 'done'>('idle');
  const [inputPrompt, setInputPrompt] = useState<string>('');
  const [fileTree, setFileTree] = useState<FileTreeNode[]>([]);

  // Center Studio Tabs
  const [activeTab, setActiveTab] = useState<'studio' | 'diffs' | 'terminal' | 'audit'>('studio');
  const [currentFile, setCurrentFile] = useState<{ path: string; content: string } | null>(null);
  const [editorMode, setEditorMode] = useState<'view' | 'edit'>('view');
  const [activeDiff, setActiveDiff] = useState<{ path: string; before: string; after: string } | null>(null);
  const [terminalOutput, setTerminalOutput] = useState<string>('');
  const [auditLogs, setAuditLogs] = useState<any[]>([]);

  // @file autocomplete
  const [showMentions, setShowMentions] = useState<boolean>(false);
  const [mentionFilter, setMentionFilter] = useState<string>('');

  const chatEndRef = useRef<HTMLDivElement>(null);

  // Apply theme to document
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('multiagent_theme', theme);
  }, [theme]);

  function toggleTheme() {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  }

  // Load health & models on mount and periodically
  useEffect(() => {
    loadHealthAndModels();
    const interval = setInterval(loadHealthAndModels, 8000);
    return () => clearInterval(interval);
  }, []);

  // When currentUser is logged in, init a fresh clean session and load file tree
  useEffect(() => {
    if (currentUser) {
      initFreshSession(currentUser);
      loadFileTree();
    }
  }, [currentUser]);

  // Auto-scroll chat window
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, steps, streamingToken]);

  async function loadHealthAndModels() {
    try {
      const h = await fetchHealth();
      setHealth(h);
      const m = await fetchModels();
      if (m.length > 0) setModels(m);
    } catch {
      setHealth(null);
    }
  }

  // Create a clean default session for user
  async function initFreshSession(userName: string) {
    try {
      const newSess = await createSession({
        name: `${userName} Workspace Session`,
        model: selectedModel,
        auto_approve_writes: autoApproveWrites,
      });
      setActiveSessionId(newSess.id);
      setAutoApproveWrites(true);
      setActiveApproval(null);
      setChatMessages([]);
      setSteps([]);
      setTerminalOutput('');
      setActiveDiff(null);
      setCurrentFile(null);
    } catch {
      // ignore
    }
  }

  async function loadFileTree(wsPath?: string) {
    try {
      const tree = await fetchFileTree(wsPath);
      setFileTree(tree);
    } catch {
      // ignore
    }
  }

  // Handle Login
  async function handleLoginSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    const u = loginUsername.trim() || (formEl.elements.namedItem('username') as HTMLInputElement)?.value?.trim() || '';
    const p = loginPassword.trim() || (formEl.elements.namedItem('password') as HTMLInputElement)?.value?.trim() || '';
    if (!u || !p) {
      setLoginError('Please enter both username and password.');
      return;
    }
    setLoginError('');
    setIsLoggingIn(true);
    try {
      const res = await loginUser(u, p);
      localStorage.setItem('multiagent_user', res.username);
      setCurrentUser(res.username);
      setLoginPassword('');
    } catch (err: any) {
      setLoginError(err.message || 'Invalid username or password.');
    } finally {
      setIsLoggingIn(false);
    }
  }

  // Handle Logout
  function handleLogout() {
    clearAuthToken();
    localStorage.removeItem('multiagent_user');
    setCurrentUser(null);
    setActiveSessionId('');
    setActiveApproval(null);
    setChatMessages([]);
    setSteps([]);
    setTerminalOutput('');
    setCurrentFile(null);
    setActiveDiff(null);
  }

  async function handleModelChange(modelName: string) {
    setSelectedModel(modelName);
    if (!activeSessionId) return;
    await updateSession(activeSessionId, { model: modelName });
  }

  async function handleToggleAutoApprove(checked: boolean) {
    setAutoApproveWrites(checked);
    if (!activeSessionId) return;
    await updateSession(activeSessionId, { auto_approve_writes: checked });
  }

  async function handleOpenFile(path: string) {
    try {
      const content = await readFile(path);
      setCurrentFile({ path, content });
      setActiveTab('studio');
    } catch (err: any) {
      alert(err.message);
    }
  }

  async function handleSaveCurrentFile() {
    if (!currentFile) return;
    try {
      await saveFile(currentFile.path, currentFile.content);
      alert(`Saved: ${currentFile.path}`);
      loadFileTree();
    } catch (err: any) {
      alert(err.message);
    }
  }

  async function handleUndoFile(path: string) {
    try {
      const res = await undoFile(path);
      if (res.success) {
        alert(`Undone changes for ${path}`);
        if (currentFile && currentFile.path === path) {
          setCurrentFile({ path, content: res.restored_content || '' });
        }
        loadFileTree();
      } else {
        alert('Undo failed: no backup found.');
      }
    } catch (err: any) {
      alert(err.message);
    }
  }

  function handleRunDemo() {
    const url = getPreviewUrl();
    window.open(url, '_blank', 'noopener,noreferrer');
  }

  async function handleApproval(approvalId: string, action: 'approve' | 'reject', autoApproveAll: boolean = false) {
    try {
      await resolveApproval(approvalId, action, autoApproveAll);
      setActiveApproval(null);
      if (autoApproveAll) {
        setAutoApproveWrites(true);
        if (activeSessionId) {
          updateSession(activeSessionId, { auto_approve_writes: true });
        }
      }
      setSteps((prev) =>
        prev.map((step) =>
          step.data?.approval_id === approvalId
            ? { ...step, data: { ...step.data, resolved: action, auto_approve_all: autoApproveAll } }
            : step
        )
      );
    } catch (err: any) {
      alert(err.message);
    }
  }

  // Trigger Pipeline Run from Right-Side Chat Window
  function handleSendMessage() {
    if (!inputPrompt.trim() || !activeSessionId || isStreaming) return;
    const promptToSend = inputPrompt.trim();
    setInputPrompt('');
    setShowMentions(false);

    // Record user message
    setChatMessages((prev) => [
      ...prev,
      {
        id: `msg_${Date.now()}`,
        sender: 'user',
        text: promptToSend,
        timestamp: Date.now(),
      },
    ]);

    setIsStreaming(true);
    setStreamingToken('');
    setCurrentStage('planner');

    let accumulatedText = '';

    streamAgentTurn(activeSessionId, promptToSend, {
      onToken: (tok) => {
        accumulatedText += tok;
        setStreamingToken(accumulatedText);
      },
      onPlan: (planSteps) => {
        setCurrentStage('coder');
        setSteps((prev) => [
          ...prev,
          {
            id: `plan_${Date.now()}`,
            type: 'plan',
            title: 'Plan Execution Steps',
            data: { steps: planSteps },
            timestamp: Date.now(),
          },
        ]);
      },
      onToolCall: (data) => {
        if (data.name === 'run_command') setCurrentStage('executor');
        else setCurrentStage('coder');
        setSteps((prev) => [
          ...prev,
          {
            id: `${data.id || 'tc'}_${Date.now()}_${Math.random()}`,
            type: 'tool_call',
            title: `Tool: ${data.name}`,
            data,
            timestamp: Date.now(),
          },
        ]);
      },
      onApprovalRequired: (data) => {
        setActiveApproval(data);
        setCurrentStage('review');
        setStreamingToken('');
        setSteps((prev) => [
          ...prev,
          {
            id: data.approval_id,
            type: 'approval_required',
            title: `Approval Required: ${data.tool}`,
            data,
            timestamp: Date.now(),
          },
        ]);
      },
      onToolResult: (data) => {
        setSteps((prev) => [
          ...prev,
          {
            id: `res_${Date.now()}`,
            type: 'tool_result',
            title: `Result: ${data.name} (${data.success ? 'Success' : 'Failed'})`,
            data,
            timestamp: Date.now(),
          },
        ]);
      },
      onFileChanged: (data) => {
        setActiveDiff(data);
        setActiveTab('diffs');
        setSteps((prev) => [
          ...prev,
          {
            id: `diff_${Date.now()}`,
            type: 'file_changed',
            title: `File Changed: ${data.path}`,
            data,
            timestamp: Date.now(),
          },
        ]);
        loadFileTree();
      },
      onTerminal: (data) => {
        setTerminalOutput((prev) => prev + `\n$ ${data.command}\n${data.output}\n`);
      },
      onError: (errMsg) => {
        setIsStreaming(false);
        setCurrentStage('idle');
        setChatMessages((prev) => [
          ...prev,
          {
            id: `err_${Date.now()}`,
            sender: 'agent',
            text: `Error: ${errMsg}`,
            timestamp: Date.now(),
          },
        ]);
      },
      onDone: () => {
        setIsStreaming(false);
        setCurrentStage('done');
        if (accumulatedText) {
          setChatMessages((prev) => [
            ...prev,
            {
              id: `done_${Date.now()}`,
              sender: 'agent',
              text: accumulatedText,
              timestamp: Date.now(),
            },
          ]);
        }
        setStreamingToken('');
      },
    });
  }

  async function handleStop() {
    if (!activeSessionId) return;
    await stopSessionTurn(activeSessionId);
    setIsStreaming(false);
    setCurrentStage('idle');
  }

  // Handle @file autocomplete
  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const val = e.target.value;
    setInputPrompt(val);

    const lastAt = val.lastIndexOf('@');
    if (lastAt !== -1 && lastAt >= val.length - 20) {
      const query = val.slice(lastAt + 1);
      if (!query.includes(' ')) {
        setMentionFilter(query.toLowerCase());
        setShowMentions(true);
        return;
      }
    }
    setShowMentions(false);
  }

  function handleSelectMention(path: string) {
    const lastAt = inputPrompt.lastIndexOf('@');
    if (lastAt !== -1) {
      const newVal = inputPrompt.slice(0, lastAt) + `@${path} ` + inputPrompt.slice(lastAt + mentionFilter.length + 1);
      setInputPrompt(newVal);
    }
    setShowMentions(false);
  }

  function getAllFilePaths(nodes: FileTreeNode[]): string[] {
    let paths: string[] = [];
    for (const node of nodes) {
      if (node.type === 'file') paths.push(node.path);
      if (node.children) paths = paths.concat(getAllFilePaths(node.children));
    }
    return paths;
  }

  const allFiles = getAllFilePaths(fileTree);
  const filteredMentionFiles = allFiles.filter((p) => p.toLowerCase().includes(mentionFilter));

  // Render tree without emojis
  function renderTree(nodes: FileTreeNode[], depth = 0) {
    return nodes.map((node) => (
      <div key={node.path} style={{ paddingLeft: `${depth * 10}px` }}>
        <div
          className={`tree-node ${currentFile?.path === node.path ? 'file-active' : ''}`}
          onClick={() => {
            if (node.type === 'file') handleOpenFile(node.path);
          }}
        >
          <span className="tree-tag">{node.type === 'directory' ? '[DIR]' : '[FILE]'}</span>
          <span>{node.name}</span>
        </div>
        {node.children && renderTree(node.children, depth + 1)}
      </div>
    ));
  }

  // Syntax line parser: removes raw '#' from comments and colors in var(--comment-color)
  function renderSyntaxLine(line: string) {
    const trimmed = line.trimStart();
    const indent = line.slice(0, line.length - trimmed.length);

    // Full-line Python/Shell/YAML comment starting with '#'
    if (trimmed.startsWith('#')) {
      const commentBody = trimmed.replace(/^#+\s*/, '');
      return (
        <>
          <span>{indent}</span>
          <span className="syntax-comment">
            <span className="comment-symbol">//</span>
            {commentBody}
          </span>
        </>
      );
    }

    // Full-line JS/TS/C comment starting with '//'
    if (trimmed.startsWith('//')) {
      const commentBody = trimmed.replace(/^\/\/+\s*/, '');
      return (
        <>
          <span>{indent}</span>
          <span className="syntax-comment">
            <span className="comment-symbol">//</span>
            {commentBody}
          </span>
        </>
      );
    }

    // Inline '#' comment
    const hashIdx = line.indexOf(' #');
    if (hashIdx !== -1) {
      const codePart = line.slice(0, hashIdx);
      const commentPart = line.slice(hashIdx + 2).replace(/^#*\s*/, '');
      return (
        <>
          <span>{codePart}  </span>
          <span className="syntax-comment">
            <span className="comment-symbol">//</span>
            {commentPart}
          </span>
        </>
      );
    }

    return <span>{line || ' '}</span>;
  }

  // -------------------------------------------------------------------------
  // Render Login Screen if not authenticated
  // -------------------------------------------------------------------------
  if (!currentUser) {
    return (
      <div className="login-screen">
        <div className="login-card">
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button className="theme-toggle" onClick={toggleTheme}>
              {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
            </button>
          </div>

          <div className="login-header">
            <span className="brand-logo-badge">MC</span>
            <h1 className="login-title">MultiAgent Code</h1>
            <p className="login-subtitle">Sign in to access workspace studio</p>
          </div>

          <form className="login-form" onSubmit={handleLoginSubmit}>
            {loginError && <div className="login-error">{loginError}</div>}

            <div className="login-field">
              <label className="login-label">Username</label>
              <input
                type="text"
                name="username"
                autoComplete="username"
                className="login-input"
                placeholder="Username (kunj, path, admin)"
                value={loginUsername}
                onChange={(e) => setLoginUsername(e.target.value)}
                autoFocus
              />
            </div>

            <div className="login-field">
              <label className="login-label">Password</label>
              <input
                type="password"
                name="password"
                autoComplete="current-password"
                className="login-input"
                placeholder="Password"
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
              />
            </div>

            <button type="submit" className="primary login-btn" disabled={isLoggingIn}>
              {isLoggingIn ? 'Authenticating...' : 'Sign In'}
            </button>
          </form>

          <div className="login-credentials-hint">
            <strong>Allowed Accounts:</strong><br />
            - kunj / kunj@123<br />
            - path / path @123<br />
            - admin / admin@123
          </div>
        </div>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Render IDE Main Workspace
  // -------------------------------------------------------------------------
  return (
    <>
      {/* App Header */}
      <header className="app-header">
        <div className="brand-container">
          <span className="brand-logo-badge">MC</span>
          <span className="brand-title">MultiAgent Code</span>

          <div className="status-badge-group">
            <span className="service-badge">
              <span className={`status-dot ${health?.services.ollama.status === 'ok' ? 'online' : 'offline'}`} />
              Ollama: {health?.services.ollama.status === 'ok' ? 'Online' : 'Offline'}
            </span>
            <span className="service-badge">
              <span className={`status-dot ${health?.services.n8n.status === 'ok' ? 'online' : 'offline'}`} />
              n8n: {health?.services.n8n.status === 'ok' ? 'Online' : 'Offline'}
            </span>
            <span className="service-badge">
              <span className={`status-dot ${health ? 'online' : 'offline'}`} />
              Backend: {health ? 'Online (:8000)' : 'Offline'}
            </span>
            <button onClick={loadHealthAndModels} style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem' }}>
              Retry
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button
            className="run-demo-btn"
            onClick={handleRunDemo}
            title="Open live working project demo in a new browser tab"
          >
            Run Project Demo [-&gt;]
          </button>

          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            User: <strong style={{ color: 'var(--accent-blue)' }}>{currentUser}</strong>
          </div>

          <button onClick={handleLogout} style={{ fontSize: '0.75rem', padding: '0.2rem 0.55rem' }}>
            Logout
          </button>

          <button className="theme-toggle" onClick={toggleTheme} title="Switch Light/Dark Theme">
            {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.8rem' }}>
            <span style={{ color: 'var(--text-muted)' }}>Model:</span>
            <select
              value={selectedModel}
              onChange={(e) => handleModelChange(e.target.value)}
              style={{ fontSize: '0.8rem' }}
            >
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        </div>
      </header>

      {/* Main 3-Column IDE Layout */}
      <div className="app-main">
        {/* Column 1: Left Sidebar (Clean File Explorer Only, No Sessions) */}
        <aside className="sidebar">
          <div className="sidebar-section-header">
            <span>Workspace Explorer</span>
            <div style={{ display: 'flex', gap: '0.35rem' }}>
              <button
                onClick={handleRunDemo}
                className="sidebar-run-btn"
                title="Open live project demo in new tab"
              >
                Run [-&gt;]
              </button>
              <button
                onClick={() => loadFileTree()}
                style={{ fontSize: '0.7rem', padding: '0.1rem 0.35rem' }}
              >
                Refresh
              </button>
            </div>
          </div>

          <div className="file-tree-container">
            {fileTree.length === 0 ? (
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', padding: '0.4rem' }}>
                (No files in workspace)
              </div>
            ) : (
              renderTree(fileTree)
            )}
          </div>

          <div style={{ padding: '0.6rem 0.8rem', borderTop: '1px solid var(--border-light)', fontSize: '0.75rem' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={autoApproveWrites}
                onChange={(e) => handleToggleAutoApprove(e.target.checked)}
              />
              <span>Auto-approve workspace writes</span>
            </label>
          </div>
        </aside>

        {/* Column 2: Center Studio (Stage Flow, Code Editor, Diffs, Terminal) */}
        <main className="center-studio">
          {/* Visual Multi-Agent Stage Flow Bar */}
          <div className="pipeline-stages-bar">
            <div className={`stage-step-item ${currentStage === 'planner' ? 'active' : currentStage !== 'idle' ? 'completed' : ''}`}>
              <span>1. Planner</span>
            </div>
            <span className="stage-arrow">-&gt;</span>

            <div className={`stage-step-item ${currentStage === 'coder' ? 'active' : ['review', 'executor', 'done'].includes(currentStage) ? 'completed' : ''}`}>
              <span>2. Code Generator</span>
            </div>
            <span className="stage-arrow">-&gt;</span>

            <div className={`stage-step-item ${currentStage === 'review' ? 'danger active' : ['executor', 'done'].includes(currentStage) ? 'completed' : ''}`}>
              <span>3. Safety &amp; Review</span>
            </div>
            <span className="stage-arrow">-&gt;</span>

            <div className={`stage-step-item ${currentStage === 'executor' ? 'active' : currentStage === 'done' ? 'completed' : ''}`}>
              <span>4. Test Runner</span>
            </div>
            <span className="stage-arrow">-&gt;</span>

            <div className={`stage-step-item ${currentStage === 'done' ? 'completed active' : ''}`}>
              <span>5. Complete</span>
              {currentStage === 'done' && (
                <button
                  className="stage-run-btn"
                  onClick={handleRunDemo}
                  title="Open working project demo in new tab"
                >
                  Run Demo [-&gt;]
                </button>
              )}
            </div>
          </div>

          {/* Project Built Success Banner */}
          {currentStage === 'done' && (
            <div className="project-done-banner">
              <div className="done-banner-info">
                <span className="done-badge">[SUCCESS] PROJECT READY</span>
                <span className="done-title">The agent finished building the project in the workspace.</span>
              </div>
              <button className="run-demo-cta-btn" onClick={handleRunDemo}>
                Open Working Project Demo in New Tab [-&gt;]
              </button>
            </div>
          )}

          {/* Active Security Approval Action Banner */}
          {activeApproval && (
            <div className="security-approval-banner">
              <div className="approval-banner-header">
                <span className="approval-banner-tag">APPROVAL REQUIRED</span>
                <span className="approval-banner-title">
                  Tool: <code>{activeApproval.tool}</code> {activeApproval.arguments?.path || activeApproval.arguments?.command || ''}
                </span>
              </div>
              <div className="approval-banner-reason">{activeApproval.reason}</div>
              <div className="approval-banner-actions">
                <button
                  className="approve-btn"
                  onClick={() => handleApproval(activeApproval.approval_id, 'approve', false)}
                >
                  Approve Operation
                </button>
                <button
                  className="approve-all-btn"
                  onClick={() => handleApproval(activeApproval.approval_id, 'approve', true)}
                >
                  Approve All Workspace Writes
                </button>
                <button
                  className="reject-btn"
                  onClick={() => handleApproval(activeApproval.approval_id, 'reject', false)}
                >
                  Reject
                </button>
              </div>
            </div>
          )}

          {/* Center Workspace Tabs */}
          <nav className="workspace-tabs">
            <button
              className={`workspace-tab ${activeTab === 'studio' ? 'active' : ''}`}
              onClick={() => setActiveTab('studio')}
            >
              Code Studio
            </button>
            <button
              className={`workspace-tab ${activeTab === 'diffs' ? 'active' : ''}`}
              onClick={() => setActiveTab('diffs')}
            >
              Diff Inspector
              {activeDiff && <span className="tab-badge" style={{ background: 'var(--accent-blue)', color: '#fff' }}>1</span>}
            </button>
            <button
              className={`workspace-tab ${activeTab === 'terminal' ? 'active' : ''}`}
              onClick={() => setActiveTab('terminal')}
            >
              Terminal
            </button>
            <button
              className={`workspace-tab ${activeTab === 'audit' ? 'active' : ''}`}
              onClick={async () => {
                setActiveTab('audit');
                const logs = await fetchAuditLogs(activeSessionId);
                setAuditLogs(logs);
              }}
            >
              Audit Logs
            </button>

            <button
              className="workspace-tab preview-tab"
              onClick={handleRunDemo}
              title="Open working project demo in new tab"
            >
              Run Demo [-&gt;]
            </button>
          </nav>

          {/* Tab Content */}
          <div className="studio-content">
            {activeTab === 'studio' && (
              <>
                <div className="code-studio-toolbar">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <span className="file-path-badge">
                      {currentFile ? currentFile.path : '(No file opened. Select a file from Workspace Explorer)'}
                    </span>
                    {currentFile && (
                      <div style={{ display: 'flex', gap: '0.35rem' }}>
                        <button
                          style={{
                            fontSize: '0.725rem',
                            padding: '0.15rem 0.45rem',
                            background: editorMode === 'view' ? 'var(--accent-blue-subtle)' : 'var(--bg-secondary)',
                            color: editorMode === 'view' ? 'var(--accent-blue)' : 'inherit',
                            borderColor: editorMode === 'view' ? 'var(--accent-blue)' : 'var(--border-medium)',
                          }}
                          onClick={() => setEditorMode('view')}
                        >
                          Syntax View (Clean Comments)
                        </button>
                        <button
                          style={{
                            fontSize: '0.725rem',
                            padding: '0.15rem 0.45rem',
                            background: editorMode === 'edit' ? 'var(--accent-blue-subtle)' : 'var(--bg-secondary)',
                            color: editorMode === 'edit' ? 'var(--accent-blue)' : 'inherit',
                            borderColor: editorMode === 'edit' ? 'var(--accent-blue)' : 'var(--border-medium)',
                          }}
                          onClick={() => setEditorMode('edit')}
                        >
                          Raw Editor
                        </button>
                      </div>
                    )}
                  </div>

                  {currentFile && (
                    <div style={{ display: 'flex', gap: '0.4rem' }}>
                      <button className="primary" onClick={handleSaveCurrentFile} style={{ fontSize: '0.75rem' }}>
                        Save File
                      </button>
                      <button onClick={() => handleUndoFile(currentFile.path)} style={{ fontSize: '0.75rem' }}>
                        Undo
                      </button>
                    </div>
                  )}
                </div>

                {currentFile ? (
                  editorMode === 'view' ? (
                    <div className="code-viewer-frame">
                      {currentFile.content.split('\n').map((line, idx) => (
                        <div key={idx} className="code-line-row">
                          <span className="line-number">{idx + 1}</span>
                          <span className="line-code">{renderSyntaxLine(line)}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <textarea
                      className="code-editor-textarea"
                      value={currentFile.content}
                      onChange={(e) => setCurrentFile({ ...currentFile, content: e.target.value })}
                    />
                  )
                ) : (
                  <div style={{ margin: 'auto', textAlign: 'center', color: 'var(--text-muted)' }}>
                    <p style={{ fontSize: '1rem', marginBottom: '0.5rem', fontWeight: 600 }}>MultiAgent Code Studio</p>
                    <p style={{ fontSize: '0.825rem' }}>Select any file in Workspace Explorer to view syntax-highlighted code with clean colored comments.</p>
                  </div>
                )}
              </>
            )}

            {activeTab === 'diffs' && (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.825rem', fontFamily: 'var(--font-mono)' }}>
                    {activeDiff ? `Diff Inspector: ${activeDiff.path}` : '(No active diff available)'}
                  </span>
                  {activeDiff && (
                    <div style={{ display: 'flex', gap: '0.4rem' }}>
                      <button className="primary" style={{ fontSize: '0.75rem' }} onClick={() => alert('Diff accepted.')}>
                        Accept Diff
                      </button>
                      <button style={{ fontSize: '0.75rem' }} onClick={() => handleUndoFile(activeDiff.path)}>
                        Undo Changes
                      </button>
                    </div>
                  )}
                </div>

                {activeDiff ? (
                  <div className="diff-container">
                    {activeDiff.before.split('\n').map((line, i) => (
                      <div key={`rem_${i}`} className="diff-line removed">
                        - {renderSyntaxLine(line)}
                      </div>
                    ))}
                    {activeDiff.after.split('\n').map((line, i) => (
                      <div key={`add_${i}`} className="diff-line added">
                        + {renderSyntaxLine(line)}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ margin: 'auto', textAlign: 'center', color: 'var(--text-muted)' }}>
                    When agents modify files, unified diffs will appear here automatically.
                  </div>
                )}
              </>
            )}

            {activeTab === 'terminal' && (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.825rem', fontWeight: 600 }}>Command Execution Terminal</span>
                  <button style={{ fontSize: '0.75rem' }} onClick={() => setTerminalOutput('')}>
                    Clear Terminal
                  </button>
                </div>
                <div className="terminal-view">
                  {terminalOutput || '(No commands executed yet. Run a pipeline task to view stdout/stderr output.)'}
                </div>
              </>
            )}

            {activeTab === 'audit' && (
              <div style={{ flex: 1, overflowY: 'auto' }}>
                <table className="audit-table">
                  <thead>
                    <tr>
                      <th>Timestamp</th>
                      <th>Tool Name</th>
                      <th>Status</th>
                      <th>Output / Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditLogs.length === 0 ? (
                      <tr>
                        <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '1rem' }}>
                          No audit records found.
                        </td>
                      </tr>
                    ) : (
                      auditLogs.map((log) => (
                        <tr key={log.id}>
                          <td>{new Date(log.timestamp * 1000).toLocaleTimeString()}</td>
                          <td>{log.tool_name}</td>
                          <td style={{ color: log.status === 'success' ? 'var(--success)' : 'inherit' }}>
                            {log.status}
                          </td>
                          <td>{log.result ? log.result.slice(0, 100) : '-'}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </main>

        {/* Column 3: Right-Side Chat Window */}
        <aside className="chat-sidebar">
          <div className="chat-sidebar-header">
            <span className="chat-header-title">Agent Chat &amp; Pipeline</span>
            <span style={{ fontSize: '0.75rem', color: isStreaming ? 'var(--accent-blue)' : 'var(--text-muted)' }}>
              {isStreaming ? 'Running...' : 'Ready'}
            </span>
          </div>

          <div className="chat-stream">
            {chatMessages.length === 0 && steps.length === 0 && !streamingToken && (
              <div className="chat-empty-state">
                <p style={{ fontWeight: 600, marginBottom: '0.4rem' }}>MultiAgent Pipeline Assistant</p>
                <p>Enter an objective below to instruct the agent. Type @file to reference workspace files.</p>
              </div>
            )}

            {/* Chat Messages */}
            {chatMessages.map((msg) => (
              <div key={msg.id} className={`chat-bubble ${msg.sender}`}>
                <span className="bubble-sender">{msg.sender === 'user' ? 'Operator' : 'Agent'}</span>
                <div className="bubble-content">{msg.text}</div>
              </div>
            ))}

            {/* Pipeline Execution Step Cards */}
            {steps.map((st) => (
              <div key={st.id} className="chat-card">
                <div className="chat-card-header">
                  <span>{st.title}</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    {new Date(st.timestamp).toLocaleTimeString()}
                  </span>
                </div>

                {st.type === 'plan' && (
                  <div className="chat-card-body">
                    <ol style={{ paddingLeft: '1.2rem' }}>
                      {st.data.steps.map((stepStr: string, idx: number) => (
                        <li key={idx} style={{ marginBottom: '0.25rem' }}>
                          {stepStr}
                        </li>
                      ))}
                    </ol>
                  </div>
                )}

                {st.type === 'tool_call' && (
                  <div className="chat-card-body">
                    <pre>{JSON.stringify(st.data.arguments, null, 2)}</pre>
                  </div>
                )}

                {st.type === 'approval_required' && (
                  <div className="approval-box">
                    <div className="approval-title-text">Approval Required: {st.data.tool}</div>
                    <div className="approval-reason-text">{st.data.reason}</div>
                    <div className="approval-args-block">{JSON.stringify(st.data.arguments, null, 2)}</div>
                    {!st.data.resolved ? (
                      <div className="approval-btn-row">
                        <button
                          className="primary"
                          onClick={() => handleApproval(st.data.approval_id, 'approve', false)}
                        >
                          Approve
                        </button>
                        <button
                          className="danger"
                          onClick={() => handleApproval(st.data.approval_id, 'reject', false)}
                        >
                          Reject
                        </button>
                        <button
                          onClick={() => handleApproval(st.data.approval_id, 'approve', true)}
                          style={{ fontSize: '0.7rem' }}
                        >
                          Approve all writes
                        </button>
                      </div>
                    ) : (
                      <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--success)' }}>
                        Status: {st.data.resolved.toUpperCase()}
                      </div>
                    )}
                  </div>
                )}

                {st.type === 'tool_result' && (
                  <div className="chat-card-body">
                    <pre>{st.data.output || JSON.stringify(st.data, null, 2)}</pre>
                  </div>
                )}

                {st.type === 'file_changed' && (
                  <div className="chat-card-body">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <strong>{st.data.path}</strong>
                      <button
                        style={{ fontSize: '0.7rem', padding: '0.1rem 0.35rem' }}
                        onClick={() => {
                          setActiveDiff(st.data);
                          setActiveTab('diffs');
                        }}
                      >
                        View Diff
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}

            {/* Live Streaming Token Box */}
            {isStreaming && streamingToken && (
              <div className="streaming-box">
                <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
                  Agent Generating...
                </div>
                <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'var(--font-mono)', fontSize: '0.775rem' }}>
                  {streamingToken}
                </div>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>

          {/* Right-Side Chat Input Area */}
          <div className="chat-input-area">
            {showMentions && filteredMentionFiles.length > 0 && (
              <div className="mention-autocomplete">
                <div style={{ padding: '0.25rem 0.5rem', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                  Reference workspace file:
                </div>
                {filteredMentionFiles.slice(0, 6).map((p) => (
                  <div key={p} className="mention-item" onClick={() => handleSelectMention(p)}>
                    @{p}
                  </div>
                ))}
              </div>
            )}

            <div className="chat-input-row">
              <textarea
                className="chat-textarea"
                placeholder="Ask or instruct the agent... Type @file to reference files. Enter to send, Shift+Enter for newline."
                value={inputPrompt}
                onChange={handleInputChange}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendMessage();
                  }
                }}
              />

              {isStreaming ? (
                <button className="danger" onClick={handleStop} style={{ height: '48px', padding: '0 0.85rem' }}>
                  Stop
                </button>
              ) : (
                <button
                  className="primary"
                  onClick={handleSendMessage}
                  disabled={!inputPrompt.trim()}
                  style={{ height: '48px', padding: '0 1rem' }}
                >
                  Send
                </button>
              )}
            </div>
          </div>
        </aside>
      </div>
    </>
  );
}
