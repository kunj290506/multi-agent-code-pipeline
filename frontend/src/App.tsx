// frontend/src/App.tsx - Clean, light, human-designed MultiAgent Code interface
import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  fetchHealth,
  fetchModelsInfo,
  fetchPreviewInfo,
  runWorkspaceProject,
  createSession,
  getSession,
  getSessionMessages,
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
  clearWorkspace,
} from './api';
import type {
  StepItem,
  HealthStatus,
  FileTreeNode,
  PreviewInfo,
} from './api';
import './index.css';

interface ChatMessage {
  id: string;
  sender: 'user' | 'agent';
  text: string;
  timestamp: number;
}

interface PreviewConsoleEntry {
  id: string;
  type: 'log' | 'warn' | 'error';
  message: string;
  ts: number;
}

const FolderIcon = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
    <path d="M2 4a1 1 0 0 1 1-1h3.5l1.5 2H13a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V4z" />
  </svg>
);

const FileIcon = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
    <path d="M4 2h5.5L13 5.5V14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" />
    <polyline points="9 2 9 6 13 6" />
  </svg>
);

export default function App() {
  // Authentication State
  const [currentUser, setCurrentUser] = useState<string | null>(() => {
    return localStorage.getItem('multiagent_user');
  });
  const [loginUsername, setLoginUsername] = useState<string>('');
  const [loginPassword, setLoginPassword] = useState<string>('');
  const [loginError, setLoginError] = useState<string>('');
  const [isLoggingIn, setIsLoggingIn] = useState<boolean>(false);
  const [failedHealthCount, setFailedHealthCount] = useState<number>(0);
  const [sessionError, setSessionError] = useState<string>('');
  const [fileTreeError, setFileTreeError] = useState<string>('');

  // Services & Models
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [models, setModels] = useState<string[]>(['qwen2.5-coder:3b', 'qwen2.5:7b-instruct-q4_K_M']);
  const [activeSessionId, setActiveSessionId] = useState<string>('');
  const [selectedModel, setSelectedModel] = useState<string>('qwen2.5-coder:3b');
  const modelInitRef = useRef<boolean>(false);
  const [autoApproveWrites, setAutoApproveWrites] = useState<boolean>(true);
  const [activeApproval, setActiveApproval] = useState<{ approval_id: string; tool: string; arguments: any; reason: string } | null>(null);

  // Chat & Pipeline State
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [steps, setSteps] = useState<StepItem[]>([]);
  const [expandedSteps, setExpandedSteps] = useState<Record<string, boolean>>({});
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [streamingToken, setStreamingToken] = useState<string>('');
  const [currentStage, setCurrentStage] = useState<'idle' | 'planner' | 'coder' | 'review' | 'executor' | 'done'>('idle');
  const [inputPrompt, setInputPrompt] = useState<string>('');
  const [fileTree, setFileTree] = useState<FileTreeNode[]>([]);
  const [isMobileChatOpen, setIsMobileChatOpen] = useState<boolean>(false);

  // Center Studio Tabs & Live Preview State
  const [activeTab, setActiveTab] = useState<'preview' | 'studio' | 'diffs' | 'terminal' | 'audit'>('studio');
  const [currentFile, setCurrentFile] = useState<{ path: string; content: string } | null>(null);
  const [editorMode, setEditorMode] = useState<'view' | 'edit'>('view');
  const [saveFeedback, setSaveFeedback] = useState<string>('');
  const [activeDiff, setActiveDiff] = useState<{ path: string; before: string; after: string } | null>(null);
  const [terminalOutput, setTerminalOutput] = useState<string>('');
  const [auditLogs, setAuditLogs] = useState<any[]>([]);

  // Live Interactive Preview State
  const [previewInfo, setPreviewInfo] = useState<PreviewInfo>({
    type: 'empty',
    entry: null,
    preview_url: '/preview/',
    command: null,
    html_files: [],
    files: [],
  });
  const [selectedPreviewFile, setSelectedPreviewFile] = useState<string>('');
  const [previewVersion, setPreviewVersion] = useState<number>(() => Date.now());
  const [previewViewport, setPreviewViewport] = useState<'desktop' | 'tablet' | 'mobile'>('desktop');
  const [previewConsole, setPreviewConsole] = useState<PreviewConsoleEntry[]>([]);
  const [showPreviewConsole, setShowPreviewConsole] = useState<boolean>(false);
  const [isRunningScript, setIsRunningScript] = useState<boolean>(false);
  const [scriptRunResult, setScriptRunResult] = useState<{
    success: boolean;
    command: string;
    returncode: number;
    output: string;
  } | null>(null);

  // @file autocomplete
  const [showMentions, setShowMentions] = useState<boolean>(false);
  const [mentionFilter, setMentionFilter] = useState<string>('');

  const chatEndRef = useRef<HTMLDivElement>(null);
  const currentFileRef = useRef<{ path: string; content: string } | null>(null);
  currentFileRef.current = currentFile;

  // Listen for unauthorized events (e.g. backend restart token invalidation)
  useEffect(() => {
    function onUnauthorized() {
      handleLogout();
    }
    window.addEventListener('auth:unauthorized', onUnauthorized);
    return () => window.removeEventListener('auth:unauthorized', onUnauthorized);
  }, []);

  // Listen for live runtime console / error events posted by the Preview iframe bridge
  useEffect(() => {
    function onPreviewMessage(ev: MessageEvent) {
      const data = ev.data;
      if (!data || data.source !== 'multiagent-preview') return;
      if (data.type === 'log' || data.type === 'warn' || data.type === 'error') {
        const entry: PreviewConsoleEntry = {
          id: `pc_${Date.now()}_${Math.random()}`,
          type: data.type,
          message: String(data.message || ''),
          ts: data.ts || Date.now(),
        };
        setPreviewConsole((prev) => [...prev.slice(-99), entry]);
        if (data.type === 'error') {
          setShowPreviewConsole(true);
        }
      }
    }
    window.addEventListener('message', onPreviewMessage);
    return () => window.removeEventListener('message', onPreviewMessage);
  }, []);

  // Load health & models on mount and periodically
  useEffect(() => {
    loadHealthAndModels();
    const interval = setInterval(loadHealthAndModels, 8000);
    return () => clearInterval(interval);
  }, []);

  // Auto-scroll chat window
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, steps, streamingToken]);

  async function loadHealthAndModels() {
    try {
      const h = await fetchHealth();
      setHealth(h);
      setFailedHealthCount(0);
      const { models: m, defaultModel } = await fetchModelsInfo();
      if (m.length > 0) {
        setModels(m);
        if (!modelInitRef.current && defaultModel) {
          modelInitRef.current = true;
          setSelectedModel(defaultModel);
        }
      }
    } catch {
      setHealth(null);
      setFailedHealthCount((prev) => prev + 1);
    }
  }

  const refreshPreviewInfo = useCallback(async (bustCache = false): Promise<PreviewInfo> => {
    const info = await fetchPreviewInfo();
    setPreviewInfo(info);
    if (info.type === 'web' && info.entry) {
      setSelectedPreviewFile((prev) => (prev && info.html_files.includes(prev) ? prev : info.entry || ''));
    } else {
      setSelectedPreviewFile('');
    }
    if (bustCache) {
      setPreviewConsole([]);
      setPreviewVersion(Date.now());
    }
    return info;
  }, []);

  const loadFileTree = useCallback(async (wsPath?: string) => {
    try {
      setFileTreeError('');
      const tree = await fetchFileTree(wsPath);
      setFileTree(tree);
      await refreshPreviewInfo(false);
    } catch (err: any) {
      setFileTreeError(err?.message || 'Failed to load file tree');
    }
  }, [refreshPreviewInfo]);

  const selectedModelRef = useRef(selectedModel);
  selectedModelRef.current = selectedModel;
  const autoApproveRef = useRef(autoApproveWrites);
  autoApproveRef.current = autoApproveWrites;

  // Restore saved session from sessionStorage or create a new session (NO workspace clearing)
  const initOrRestoreSession = useCallback(async (userName: string) => {
    setSessionError('');
    const savedSessionId = sessionStorage.getItem('multiagent_session_id');
    if (savedSessionId) {
      try {
        const sess = await getSession(savedSessionId);
        if (sess) {
          setActiveSessionId(sess.id);
          if (sess.model) setSelectedModel(sess.model);
          if (sess.auto_approve_writes !== undefined) setAutoApproveWrites(sess.auto_approve_writes);

          try {
            const msgs = await getSessionMessages(sess.id);
            setChatMessages(
              msgs.map((m) => ({
                id: m.id,
                sender: m.role === 'user' ? 'user' : 'agent',
                text: m.content,
                timestamp: m.created_at ? m.created_at * 1000 : Date.now(),
              }))
            );
          } catch {
            // Keep active session even if messages fail
          }
          await loadFileTree();
          return;
        }
      } catch {
        // Fallback to creating a new session
      }
    }

    try {
      const newSess = await createSession({
        name: `${userName} Workspace Session`,
        model: selectedModelRef.current,
        auto_approve_writes: autoApproveRef.current,
      });
      sessionStorage.setItem('multiagent_session_id', newSess.id);
      setActiveSessionId(newSess.id);
      setChatMessages([]);
      setSteps([]);
      setTerminalOutput('');
      setActiveDiff(null);
      setCurrentFile(null);
      setScriptRunResult(null);
      setPreviewConsole([]);
      await loadFileTree();
    } catch (err: any) {
      setSessionError(err?.message || 'Failed to create session');
    }
  }, [loadFileTree]);

  // When currentUser is logged in, restore or init session without clearing workspace
  useEffect(() => {
    if (currentUser) {
      initOrRestoreSession(currentUser);
    }
  }, [currentUser, initOrRestoreSession]);

  // Explicit New Session button: clears workspace and creates a fresh session
  async function handleNewSession() {
    if (!currentUser) return;
    try {
      setSessionError('');
      await clearWorkspace();
      sessionStorage.removeItem('multiagent_session_id');
      setFileTree([]);
      setCurrentFile(null);
      setActiveDiff(null);
      setChatMessages([]);
      setSteps([]);
      setTerminalOutput('');
      setScriptRunResult(null);
      setPreviewConsole([]);
      setCurrentStage('idle');
      setActiveTab('studio');
      const newSess = await createSession({
        name: `${currentUser} Workspace Session`,
        model: selectedModel,
        auto_approve_writes: autoApproveWrites,
      });
      sessionStorage.setItem('multiagent_session_id', newSess.id);
      setActiveSessionId(newSess.id);
      await loadFileTree();
    } catch (err: any) {
      setSessionError(err?.message || 'Failed to create new session');
    }
  }

  // Handle Login: explicit login submit clears workspace and resets session
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
      await clearWorkspace();
      sessionStorage.removeItem('multiagent_session_id');
      localStorage.setItem('multiagent_user', res.username);
      setFileTree([]);
      setCurrentFile(null);
      setActiveDiff(null);
      setPreviewConsole([]);
      setScriptRunResult(null);
      setActiveTab('studio');
      setCurrentUser(res.username);
      setLoginPassword('');
    } catch (err: any) {
      setLoginError(err?.message || 'Invalid username or password.');
    } finally {
      setIsLoggingIn(false);
    }
  }

  // Handle Logout
  function handleLogout() {
    clearAuthToken();
    localStorage.removeItem('multiagent_user');
    sessionStorage.removeItem('multiagent_session_id');
    setCurrentUser(null);
    setActiveSessionId('');
    setActiveApproval(null);
    setChatMessages([]);
    setSteps([]);
    setTerminalOutput('');
    setCurrentFile(null);
    setActiveDiff(null);
    setFileTree([]);
    setPreviewConsole([]);
    setScriptRunResult(null);
    setPreviewInfo({
      type: 'empty',
      entry: null,
      preview_url: '/preview/',
      command: null,
      html_files: [],
      files: [],
    });
    setActiveTab('studio');
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
      alert(err?.message || 'Could not read file');
    }
  }

  async function handleSaveCurrentFile() {
    if (!currentFile) return;
    try {
      await saveFile(currentFile.path, currentFile.content);
      setSaveFeedback('Saved');
      setTimeout(() => setSaveFeedback(''), 1800);
      await loadFileTree();
      await refreshPreviewInfo(true);
    } catch (err: any) {
      alert(err?.message || 'Could not save file');
    }
  }

  async function handleUndoFile(path: string) {
    try {
      const res = await undoFile(path);
      if (res.success) {
        if (currentFile && currentFile.path === path) {
          setCurrentFile({ path, content: res.restored_content || '' });
        }
        await loadFileTree();
        await refreshPreviewInfo(true);
      } else {
        alert('Undo failed: no backup found.');
      }
    } catch (err: any) {
      alert(err?.message || 'Could not undo changes');
    }
  }

  async function handleRunScript(entry?: string) {
    setIsRunningScript(true);
    try {
      const res = await runWorkspaceProject(entry ? { entry } : {});
      setScriptRunResult(res);
      setTerminalOutput((prev) => prev + `\n$ ${res.command}\n${res.output}\n`);
    } catch (err: any) {
      setScriptRunResult({
        success: false,
        command: entry || previewInfo.command || 'run',
        returncode: 1,
        output: err?.message || 'Failed to execute script.',
      });
    } finally {
      setIsRunningScript(false);
    }
  }

  function handleRunDemo() {
    // Open synchronously inside the click event so browsers never block the new tab
    const targetFile = selectedPreviewFile || (previewInfo.type === 'web' && previewInfo.entry ? previewInfo.entry : '');
    const url = getPreviewUrl(targetFile, Date.now());
    window.open(url, '_blank', 'noopener,noreferrer');

    // Keep the embedded Studio Preview tab refreshed in sync as well
    refreshPreviewInfo(true).then((info) => {
      if (info.type === 'python' || info.type === 'node') {
        handleRunScript(info.entry || undefined);
      }
    });
  }

  function handleOpenPreviewNewTab() {
    const targetFile = selectedPreviewFile || (previewInfo.type === 'web' && previewInfo.entry ? previewInfo.entry : '');
    const url = getPreviewUrl(targetFile, Date.now());
    window.open(url, '_blank', 'noopener,noreferrer');
  }

  function handleFixPreviewErrors() {
    const errorMsgs = previewConsole.filter((e) => e.type === 'error').map((e) => e.message);
    const valMsgs = previewInfo.validation?.errors || [];
    const combined = Array.from(new Set([...errorMsgs, ...valMsgs]));
    if (combined.length === 0) return;
    const entryName = selectedPreviewFile || previewInfo.entry || 'index.html';
    const fixPrompt =
      `Fix the following runtime/validation errors in ${entryName} so every button, input, and interaction works cleanly:\n` +
      combined.map((e) => `- ${e}`).join('\n');
    handleSendPrompt(fixPrompt);
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
      alert(err?.message || 'Could not resolve approval');
    }
  }

  function handleSendPrompt(promptText: string) {
    if (!promptText.trim() || !activeSessionId || isStreaming) return;
    const promptToSend = promptText.trim();
    setInputPrompt('');
    setShowMentions(false);

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
    let changedFilesInTurn: string[] = [];

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
            id: `plan_${Date.now()}_${Math.random()}`,
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
        accumulatedText = '';
        setStreamingToken('');
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
        if (data.name === 'verify_project') {
          setCurrentStage('review');
        }
        setSteps((prev) => [
          ...prev,
          {
            id: `res_${Date.now()}_${Math.random()}`,
            type: 'tool_result',
            title: `Result: ${data.name} (${data.success ? 'Success' : 'Failed'})`,
            data,
            timestamp: Date.now(),
          },
        ]);
      },
      onFileChanged: (data) => {
        changedFilesInTurn.push(data.path);
        setActiveDiff(data);
        // Keep open Studio editor synchronized with agent edits (or auto-open first created file)
        if (!currentFileRef.current || currentFileRef.current.path === data.path) {
          setCurrentFile({ path: data.path, content: data.after });
        }
        setSteps((prev) => [
          ...prev,
          {
            id: `diff_${Date.now()}_${Math.random()}`,
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
      onDone: async (doneData) => {
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

        const modifiedList: string[] = Array.isArray(doneData?.files_modified) && doneData.files_modified.length > 0
          ? doneData.files_modified
          : changedFilesInTurn;

        await loadFileTree();
        if (modifiedList.length > 0) {
          const info = await refreshPreviewInfo(true);
          if (info.type === 'web') {
            setActiveTab('preview');
          } else if (info.type === 'python' || info.type === 'node') {
            setActiveTab('preview');
            await handleRunScript(info.entry || undefined);
          }
        }
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

  // Render tree with inline SVG glyphs and 12px indentation
  function renderTree(nodes: FileTreeNode[], depth = 0) {
    return nodes.map((node) => (
      <div key={node.path}>
        <div
          className={`tree-row ${currentFile?.path === node.path ? 'selected' : ''}`}
          style={{ paddingLeft: `${16 + depth * 12}px` }}
          onClick={() => {
            if (node.type === 'file') handleOpenFile(node.path);
          }}
        >
          <span className="tree-glyph">
            {node.type === 'directory' ? <FolderIcon /> : <FileIcon />}
          </span>
          <span>{node.name}</span>
        </div>
        {node.children && renderTree(node.children, depth + 1)}
      </div>
    ));
  }

  // Light syntax highlighting parser
  function renderSyntaxLine(line: string) {
    const trimmed = line.trimStart();
    const indent = line.slice(0, line.length - trimmed.length);

    if (trimmed.startsWith('#') || trimmed.startsWith('//')) {
      return (
        <>
          <span>{indent}</span>
          <span className="syntax-comment">{trimmed}</span>
        </>
      );
    }

    const tokenRegex = /(#[^'"]*$|\/\/[^'"]*$|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b(?:def|class|import|from|return|if|else|elif|for|while|try|except|finally|with|as|pass|break|continue|lambda|yield|const|let|var|function|export|async|await|switch|case|new|this|typeof|void|in|of|print)\b|[a-zA-Z_]\w*|[^\s\w]+|\s+)/g;
    const parts = line.match(tokenRegex) || [line];
    const keywords = new Set([
      'def', 'class', 'import', 'from', 'return', 'if', 'else', 'elif', 'for', 'while',
      'try', 'except', 'finally', 'with', 'as', 'pass', 'break', 'continue', 'lambda', 'yield',
      'const', 'let', 'var', 'function', 'export', 'async', 'await', 'switch', 'case', 'new',
      'this', 'typeof', 'void', 'in', 'of', 'print',
    ]);

    return (
      <>
        {parts.map((part, i) => {
          if (part.startsWith('#') || part.startsWith('//')) {
            return <span key={i} className="syntax-comment">{part}</span>;
          }
          if ((part.startsWith('"') && part.endsWith('"')) || (part.startsWith("'") && part.endsWith("'"))) {
            return <span key={i} className="syntax-string">{part}</span>;
          }
          if (keywords.has(part)) {
            return <span key={i} className="syntax-keyword">{part}</span>;
          }
          return <span key={i}>{part}</span>;
        })}
      </>
    );
  }

  function getStepTitle(st: StepItem): string {
    if (st.type === 'plan') {
      const count = st.data?.steps?.length || 0;
      return count > 0 ? `Planned ${count} execution steps` : 'Execution plan';
    }
    if (st.type === 'tool_call') {
      const name = st.data?.name;
      if (name === 'read_file') return `Read ${st.data?.arguments?.path || ''}`;
      if (name === 'write_file') return `Wrote ${st.data?.arguments?.path || ''}`;
      if (name === 'edit_file') return `Edited ${st.data?.arguments?.path || ''}`;
      if (name === 'run_command') return `Run: ${st.data?.arguments?.command || ''}`;
      return `Tool: ${name || 'call'}`;
    }
    if (st.type === 'tool_result') {
      return `Result: ${st.data?.name || 'tool'} (${st.data?.success ? 'success' : 'failed'})`;
    }
    if (st.type === 'file_changed') {
      return `Edited ${st.data?.path || 'file'} — view diff`;
    }
    if (st.type === 'approval_required') {
      return `Approval needed: ${st.data?.tool || 'action'}`;
    }
    return st.title || 'Step';
  }

  function toggleStep(id: string) {
    setExpandedSteps((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  const backendUrl = typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:8000';
  const offlineBanner = failedHealthCount >= 2 ? (
    <div id="backend-offline-banner" className="offline-banner">
      <span className="status-dot offline" />
      <span>Backend not reachable at {backendUrl}. Check that python start.py is running</span>
    </div>
  ) : null;

  const isAnyServiceOffline = !health || health.services.ollama.status !== 'ok' || health.services.n8n.status !== 'ok';

  // -------------------------------------------------------------------------
  // Render Login Screen if not authenticated (Rule 12: 360px centered card)
  // -------------------------------------------------------------------------
  if (!currentUser) {
    return (
      <div className="login-page">
        {offlineBanner}
        <div className="login-card">
          <div className="login-header">
            <h1 className="login-title">MultiAgent Code</h1>
            <p className="login-subtitle">Sign in to access your workspace</p>
          </div>

          <form className="login-form" onSubmit={handleLoginSubmit}>
            {loginError && <div className="login-error">{loginError}</div>}

            <div className="form-group">
              <label className="form-label" htmlFor="login-username">Username</label>
              <input
                id="login-username"
                type="text"
                name="username"
                autoComplete="username"
                className="input-text"
                placeholder="Username"
                value={loginUsername}
                onChange={(e) => setLoginUsername(e.target.value)}
                autoFocus
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="login-password">Password</label>
              <input
                id="login-password"
                type="password"
                name="password"
                autoComplete="current-password"
                className="input-text"
                placeholder="Password"
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
              />
            </div>

            <button type="submit" className="btn-primary" disabled={isLoggingIn} style={{ height: '36px', width: '100%', marginTop: '4px' }}>
              {isLoggingIn ? 'Signing in...' : 'Sign in'}
            </button>
          </form>

          <div className="login-hint">
            Accounts: kunj / kunj@123 · path / path@123 · admin / admin@123
          </div>
        </div>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Render Main Workspace
  // -------------------------------------------------------------------------
  const isTurnRunning = currentStage !== 'idle' || isStreaming;
  const previewErrorCount = previewConsole.filter((e) => e.type === 'error').length;
  const validationErrorCount = previewInfo.validation?.errors?.length || 0;
  const totalPreviewErrors = previewErrorCount + validationErrorCount;
  const activePreviewEntry = selectedPreviewFile || previewInfo.entry || '';
  const activeIframeUrl = getPreviewUrl(activePreviewEntry, previewVersion);

  const timelineItems = [
    ...chatMessages.map((msg) => ({ kind: 'message' as const, ts: msg.timestamp, msg })),
    ...steps.map((st) => ({ kind: 'step' as const, ts: st.timestamp, st })),
  ].sort((a, b) => a.ts - b.ts);

  return (
    <>
      {offlineBanner}

      {/* Header: 52px single row (Rule 6) */}
      <header className="app-header">
        <span className="header-brand">MultiAgent Code</span>

        <div className="header-right">
          {previewInfo.type !== 'empty' && (
            <button
              className="btn-primary btn-sm"
              onClick={handleRunDemo}
              title="Open live demo in a new browser tab"
            >
              ▶ Run demo ↗
            </button>
          )}

          <button className="btn-secondary" onClick={handleNewSession} title="Reset workspace and start a new session">
            New session
          </button>

          <select
            className="header-select"
            value={selectedModel}
            onChange={(e) => handleModelChange(e.target.value)}
            title="Select language model"
          >
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>

          <div className="services-dropdown">
            <div className="services-trigger">
              <span>Services</span>
              <span className={`status-dot ${health?.services.ollama.status === 'ok' ? 'online' : 'offline'}`} />
              <span className={`status-dot ${health ? 'online' : 'offline'}`} />
              <span className={`status-dot ${health?.services.n8n.status === 'ok' ? 'online' : 'offline'}`} />
            </div>
            <div className="services-popover">
              <div className="services-row">
                <span className={`status-dot ${health?.services.ollama.status === 'ok' ? 'online' : 'offline'}`} />
                <span>Ollama: {health?.services.ollama.status === 'ok' ? 'Online' : 'Offline'}</span>
              </div>
              <div className="services-row">
                <span className={`status-dot ${health ? 'online' : 'offline'}`} />
                <span>Backend: {health ? 'Online (:8000)' : 'Offline'}</span>
              </div>
              <div 
                className="services-row" 
                style={{ cursor: 'pointer' }} 
                onClick={() => window.open('http://localhost:5678', '_blank')}
                title="Open official n8n in Docker (:5678)"
              >
                <span className={`status-dot ${health?.services.n8n.status === 'ok' ? 'online' : 'offline'}`} />
                <span style={{ textDecoration: 'underline' }}>
                  n8n: {health?.services.n8n.status === 'ok' ? 'Online (:5678) ↗' : 'Offline'}
                </span>
              </div>
            </div>
          </div>

          {isAnyServiceOffline && (
            <button className="btn-link" onClick={loadHealthAndModels} title="Retry checking services">
              Retry
            </button>
          )}

          <span className="header-user">{currentUser}</span>

          <button className="btn-link" onClick={handleLogout}>
            Log out
          </button>

          <button
            className="btn-secondary mobile-chat-toggle"
            onClick={() => setIsMobileChatOpen(!isMobileChatOpen)}
          >
            Chat
          </button>
        </div>
      </header>

      {/* Slim Step Indicator: Visible only during an active turn (Rule 7) */}
      {isTurnRunning && (
        <div className="stage-indicator">
          {(() => {
            const stageOrder: Array<'planner' | 'coder' | 'review' | 'executor' | 'done'> = [
              'planner',
              'coder',
              'review',
              'executor',
              'done',
            ];
            const labels = {
              planner: 'Planner',
              coder: 'Code generator',
              review: 'Review',
              executor: 'Test runner',
              done: 'Complete',
            };
            const currentIndex = stageOrder.indexOf(currentStage as any);

            return stageOrder.map((stg, idx) => {
              const isPast = currentIndex > idx;
              const isCurrent = currentIndex === idx;

              return (
                <React.Fragment key={stg}>
                  {idx > 0 && <span className="stage-separator">/</span>}
                  <span className={`stage-step ${isCurrent ? 'active' : isPast ? 'completed' : ''}`}>
                    {isPast ? (
                      <span className="stage-check">✓</span>
                    ) : isCurrent ? (
                      <span className="status-dot active" />
                    ) : (
                      <span className="status-dot" style={{ backgroundColor: '#D1CFCA' }} />
                    )}
                    <span>{labels[stg]}</span>
                  </span>
                </React.Fragment>
              );
            });
          })()}

          {currentStage === 'done' && (
            <button className="btn-primary btn-sm stage-run-demo" onClick={handleRunDemo}>
              Run demo
            </button>
          )}
        </div>
      )}

      {/* Main 3-Column Layout (Rule 5) */}
      <div className="app-main">
        {/* Column 1: Left Explorer (240px) (Rule 8) */}
        <aside className="explorer-panel">
          <div className="panel-header">
            <span className="panel-title">Files</span>
          </div>

          <div className="tree-container">
            {fileTreeError ? (
              <div className="tree-empty" style={{ color: 'var(--status-red)' }}>
                {fileTreeError}
              </div>
            ) : fileTree.length === 0 ? (
              <div className="tree-empty">
                This workspace is empty. Ask the agent to create something.
              </div>
            ) : (
              renderTree(fileTree)
            )}
          </div>

          <div className="explorer-footer">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={autoApproveWrites}
                onChange={(e) => handleToggleAutoApprove(e.target.checked)}
              />
              <span className="checkbox-title">Auto-approve file changes</span>
            </label>
            <div className="checkbox-explanation">
              Apply file edits without prompting for confirmation.
            </div>
          </div>
        </aside>

        {/* Column 2: Center Studio (Rule 9) */}
        <main className="studio-panel">
          {sessionError && (
            <div style={{ padding: '8px 16px', background: 'var(--bg-accent-subtle)', color: 'var(--status-red)', fontSize: '13px', borderBottom: '1px solid var(--border)' }}>
              {sessionError}
            </div>
          )}

          <nav className="studio-tabs">
            <button
              className={`studio-tab ${activeTab === 'preview' ? 'active' : ''}`}
              onClick={() => {
                setActiveTab('preview');
                refreshPreviewInfo(false);
              }}
            >
              <span className="tab-label-row">
                {previewInfo.type !== 'empty' && (
                  <span className={`status-dot ${totalPreviewErrors > 0 ? 'offline' : 'online'}`} />
                )}
                <span>Preview</span>
                {totalPreviewErrors > 0 && (
                  <span className="tab-error-badge">{totalPreviewErrors}</span>
                )}
              </span>
            </button>
            <button
              className={`studio-tab ${activeTab === 'studio' ? 'active' : ''}`}
              onClick={() => setActiveTab('studio')}
            >
              Code
            </button>
            <button
              className={`studio-tab ${activeTab === 'diffs' ? 'active' : ''}`}
              onClick={() => setActiveTab('diffs')}
            >
              Diffs {activeDiff && ' (1)'}
            </button>
            <button
              className={`studio-tab ${activeTab === 'terminal' ? 'active' : ''}`}
              onClick={() => setActiveTab('terminal')}
            >
              Terminal
            </button>
            <button
              className={`studio-tab ${activeTab === 'audit' ? 'active' : ''}`}
              onClick={async () => {
                setActiveTab('audit');
                const logs = await fetchAuditLogs(activeSessionId);
                setAuditLogs(logs);
              }}
            >
              Audit
            </button>
          </nav>

          <div className="studio-body">
            {/* Live Interactive Preview Tab */}
            {activeTab === 'preview' && (
              <div className="preview-panel">
                {previewInfo.type === 'web' ? (
                  <>
                    <div className="preview-toolbar">
                      <div className="preview-toolbar-left">
                        <button
                          className="btn-secondary btn-sm"
                          onClick={() => refreshPreviewInfo(true)}
                          title="Reload live preview"
                        >
                          ↻ Reload
                        </button>

                        {previewInfo.html_files.length > 1 ? (
                          <select
                            className="preview-url-select"
                            value={activePreviewEntry}
                            onChange={(e) => {
                              setSelectedPreviewFile(e.target.value);
                              setPreviewConsole([]);
                              setPreviewVersion(Date.now());
                            }}
                            title="Select HTML page to preview"
                          >
                            {previewInfo.html_files.map((hf) => (
                              <option key={hf} value={hf}>
                                /preview/{hf}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="preview-url-pill" title="Live preview endpoint">
                            /preview/{activePreviewEntry || 'index.html'}
                          </span>
                        )}
                      </div>

                      <div className="preview-toolbar-right">
                        <div className="viewport-group" role="group" aria-label="Viewport size">
                          <button
                            className={`viewport-btn ${previewViewport === 'desktop' ? 'active' : ''}`}
                            onClick={() => setPreviewViewport('desktop')}
                            title="Desktop view (100%)"
                          >
                            Desktop
                          </button>
                          <button
                            className={`viewport-btn ${previewViewport === 'tablet' ? 'active' : ''}`}
                            onClick={() => setPreviewViewport('tablet')}
                            title="Tablet view (768px)"
                          >
                            Tablet
                          </button>
                          <button
                            className={`viewport-btn ${previewViewport === 'mobile' ? 'active' : ''}`}
                            onClick={() => setPreviewViewport('mobile')}
                            title="Mobile view (390px)"
                          >
                            Mobile
                          </button>
                        </div>

                        <button
                          className={`btn-secondary btn-sm ${previewErrorCount > 0 ? 'btn-error-outline' : ''}`}
                          onClick={() => setShowPreviewConsole((prev) => !prev)}
                          title="Toggle live preview console"
                        >
                          Console{previewConsole.length > 0 ? ` (${previewConsole.length})` : ''}
                        </button>

                        <button
                          className="btn-secondary btn-sm"
                          onClick={handleOpenPreviewNewTab}
                          title="Open live demo in a new browser tab"
                        >
                          Open tab ↗
                        </button>
                      </div>
                    </div>

                    {totalPreviewErrors > 0 && (
                      <div className="preview-error-banner">
                        <div className="preview-error-summary">
                          <span className="status-dot offline" />
                          <span>
                            {previewErrorCount > 0
                              ? `Runtime error in preview: ${previewConsole.find((e) => e.type === 'error')?.message}`
                              : `Validation warning: ${previewInfo.validation?.errors[0]}`}
                          </span>
                        </div>
                        <button
                          className="btn-primary btn-sm"
                          onClick={handleFixPreviewErrors}
                          disabled={isStreaming}
                        >
                          Fix with Assistant
                        </button>
                      </div>
                    )}

                    <div className={`preview-stage viewport-${previewViewport}`}>
                      <iframe
                        key={`${activePreviewEntry}_${previewVersion}`}
                        src={activeIframeUrl}
                        title="Live Project Demo Preview"
                        className="preview-iframe"
                        allow="clipboard-read; clipboard-write; fullscreen"
                      />
                    </div>

                    {showPreviewConsole && (
                      <div className="preview-console">
                        <div className="preview-console-header">
                          <span>Preview Console ({previewConsole.length})</span>
                          <div style={{ display: 'flex', gap: '8px' }}>
                            {previewErrorCount > 0 && (
                              <button
                                className="btn-primary btn-sm"
                                onClick={handleFixPreviewErrors}
                                disabled={isStreaming}
                              >
                                Fix errors
                              </button>
                            )}
                            <button className="btn-link" onClick={() => setPreviewConsole([])}>
                              Clear
                            </button>
                            <button className="btn-link" onClick={() => setShowPreviewConsole(false)}>
                              Close
                            </button>
                          </div>
                        </div>
                        <div className="preview-console-body">
                          {previewConsole.length === 0 ? (
                            <div className="preview-console-empty">No console output or runtime errors.</div>
                          ) : (
                            previewConsole.map((entry) => (
                              <div key={entry.id} className={`preview-console-line level-${entry.type}`}>
                                <span className="console-badge">{entry.type.toUpperCase()}</span>
                                <span className="console-msg">{entry.message}</span>
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    )}
                  </>
                ) : previewInfo.type === 'python' || previewInfo.type === 'node' ? (
                  <>
                    <div className="preview-toolbar">
                      <div className="preview-toolbar-left">
                        <span className="preview-url-pill">{previewInfo.command || previewInfo.entry}</span>
                        {scriptRunResult && (
                          <span
                            className={`run-exit-badge ${scriptRunResult.success ? 'ok' : 'err'}`}
                          >
                            Exit {scriptRunResult.returncode}
                          </span>
                        )}
                      </div>
                      <div className="preview-toolbar-right">
                        <button
                          className="btn-primary btn-sm"
                          onClick={() => handleRunScript(previewInfo.entry || undefined)}
                          disabled={isRunningScript}
                        >
                          {isRunningScript ? 'Running...' : `▶ Run ${previewInfo.entry}`}
                        </button>
                        {previewInfo.entry && (
                          <button
                            className="btn-secondary btn-sm"
                            onClick={() => handleOpenFile(previewInfo.entry!)}
                          >
                            View code
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="script-runner-body">
                      {scriptRunResult ? (
                        <>
                          <div className="script-runner-cmd">$ {scriptRunResult.command}</div>
                          <pre className="script-runner-output">
                            {scriptRunResult.output || '(Process finished with no output)'}
                          </pre>
                          {!scriptRunResult.success && (
                            <div style={{ marginTop: '12px' }}>
                              <button
                                className="btn-primary btn-sm"
                                disabled={isStreaming}
                                onClick={() =>
                                  handleSendPrompt(
                                    `Fix the error when running \`${scriptRunResult.command}\`:\n${scriptRunResult.output}`
                                  )
                                }
                              >
                                Fix error with Assistant
                              </button>
                            </div>
                          )}
                        </>
                      ) : (
                        <div className="studio-empty">
                          <h2 className="studio-empty-title">Ready to run {previewInfo.entry}</h2>
                          <p style={{ color: 'var(--text-muted)', fontSize: '13px', marginBottom: '12px' }}>
                            Click &ldquo;Run {previewInfo.entry}&rdquo; above to execute this {previewInfo.type} project inside the sandbox and inspect live output.
                          </p>
                          <button
                            className="btn-primary btn-sm"
                            onClick={() => handleRunScript(previewInfo.entry || undefined)}
                            disabled={isRunningScript}
                          >
                            ▶ Run {previewInfo.entry}
                          </button>
                        </div>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="studio-empty">
                    <h2 className="studio-empty-title">No live demo built yet</h2>
                    <ul className="studio-empty-hints">
                      <li>Pick a sample prompt on the right or describe any web app, game, or script</li>
                      <li>The agent will build, verify for syntax &amp; interactivity bugs, and launch the live preview automatically</li>
                      <li>You can interact with your app directly here or pop it out in a full browser tab</li>
                    </ul>
                  </div>
                )}
              </div>
            )}

            {/* Studio / Code Tab */}
            {activeTab === 'studio' && (
              <>
                {currentFile ? (
                  <>
                    <div className="studio-toolbar">
                      <span className="file-path">{currentFile.path}</span>

                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        {saveFeedback && (
                          <span style={{ fontSize: '12px', color: 'var(--status-green)', fontWeight: 500 }}>
                            {saveFeedback}
                          </span>
                        )}
                        <button
                          className={editorMode === 'view' ? 'btn-secondary btn-sm' : 'btn-link'}
                          onClick={() => setEditorMode('view')}
                        >
                          View
                        </button>
                        <button
                          className={editorMode === 'edit' ? 'btn-secondary btn-sm' : 'btn-link'}
                          onClick={() => setEditorMode('edit')}
                        >
                          Edit
                        </button>
                        {editorMode === 'edit' && (
                          <button className="btn-primary btn-sm" onClick={handleSaveCurrentFile}>
                            Save
                          </button>
                        )}
                        <button className="btn-secondary btn-sm" onClick={() => handleUndoFile(currentFile.path)}>
                          Undo
                        </button>
                        <button className="btn-primary btn-sm" onClick={handleRunDemo} title="Open live demo in a new browser tab">
                          ▶ Run demo ↗
                        </button>
                      </div>
                    </div>

                    {editorMode === 'view' ? (
                      <div className="code-viewer">
                        {currentFile.content.split('\n').map((line, idx) => (
                          <div key={idx} className="code-line">
                            <span className="line-number">{idx + 1}</span>
                            <span className="line-content">{renderSyntaxLine(line)}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <textarea
                        className="code-textarea"
                        value={currentFile.content}
                        onChange={(e) => setCurrentFile({ ...currentFile, content: e.target.value })}
                        onKeyDown={(e) => {
                          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
                            e.preventDefault();
                            handleSaveCurrentFile();
                          }
                        }}
                        spellCheck={false}
                      />
                    )}
                  </>
                ) : (
                  <div className="studio-empty">
                    <h2 className="studio-empty-title">No file open</h2>
                    <ul className="studio-empty-hints">
                      <li>Select a file from the list on the left to view or edit it</li>
                      <li>Ask the assistant in the chat to create or modify files</li>
                      <li>Generated web apps open automatically in the interactive Preview tab</li>
                    </ul>
                  </div>
                )}
              </>
            )}

            {/* Diffs Tab */}
            {activeTab === 'diffs' && (
              <>
                {activeDiff ? (
                  <>
                    <div className="studio-toolbar">
                      <span className="file-path">{activeDiff.path}</span>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        <button className="btn-secondary btn-sm" onClick={() => handleUndoFile(activeDiff.path)}>
                          Undo changes
                        </button>
                      </div>
                    </div>
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
                  </>
                ) : (
                  <div className="studio-empty">
                    <h2 className="studio-empty-title">No changes to display</h2>
                    <p style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
                      When the assistant edits a file, unified line-by-line diffs will appear here.
                    </p>
                  </div>
                )}
              </>
            )}

            {/* Terminal Tab */}
            {activeTab === 'terminal' && (
              <>
                <div className="studio-toolbar">
                  <span className="file-path">Terminal Output</span>
                  <button className="btn-secondary btn-sm" onClick={() => setTerminalOutput('')}>
                    Clear
                  </button>
                </div>
                <div className="terminal-viewer">
                  {terminalOutput || 'No terminal commands run yet.'}
                </div>
              </>
            )}

            {/* Audit Tab */}
            {activeTab === 'audit' && (
              <div className="audit-table-wrap">
                <table className="audit-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Tool</th>
                      <th>Status</th>
                      <th>Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditLogs.length === 0 ? (
                      <tr>
                        <td colSpan={4} style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '16px' }}>
                          No audit records found.
                        </td>
                      </tr>
                    ) : (
                      auditLogs.map((log) => (
                        <tr key={log.id}>
                          <td>{new Date(log.timestamp * 1000).toLocaleTimeString()}</td>
                          <td>{log.tool_name}</td>
                          <td>
                            <span style={{ color: log.status === 'success' ? 'var(--status-green)' : 'var(--status-red)' }}>
                              {log.status}
                            </span>
                          </td>
                          <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                            {log.result ? log.result.slice(0, 100) : '-'}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </main>

        {/* Column 3: Right Chat (380px) (Rule 10) */}
        <aside className={`chat-panel ${isMobileChatOpen ? 'open' : ''}`}>
          <div className="panel-header">
            <span className="panel-title">Assistant</span>
            {isStreaming && (
              <span style={{ fontSize: '12px', color: 'var(--accent)', fontWeight: 500 }}>
                Thinking...
              </span>
            )}
          </div>

          <div className="chat-messages">
            {chatMessages.length === 0 && steps.length === 0 && !streamingToken && (
              <div className="chat-empty">
                <div className="chat-empty-heading">What would you like to build?</div>
                <div className="chat-prompts">
                  <button
                    className="prompt-suggestion"
                    onClick={() =>
                      handleSendPrompt(
                        'Write a complete interactive Calculator with buttons for numbers 0-9, decimal point, arithmetic operations (+, -, *, /), backspace, keyboard support, a display screen, clear button, and modern dark CSS styling into index.html using write_file.'
                      )
                    }
                  >
                    Interactive Dark-Theme Calculator
                  </button>
                  <button
                    className="prompt-suggestion"
                    onClick={() =>
                      handleSendPrompt(
                        'Write a complete interactive To-Do List web application with an input field to add tasks, checkboxes to mark items done, filter tabs (All/Active/Completed), delete buttons, live task counter, and clean modern styling into index.html using write_file.'
                      )
                    }
                  >
                    Minimalist To-Do List App
                  </button>
                  <button
                    className="prompt-suggestion"
                    onClick={() =>
                      handleSendPrompt(
                        'Write a complete interactive 3x3 Tic-Tac-Toe game with player turns (X and O), win and tie detection with highlighted winning cells, score counters, and restart game button into index.html using write_file.'
                      )
                    }
                  >
                    Interactive 3x3 Tic-Tac-Toe Game
                  </button>
                  <button
                    className="prompt-suggestion"
                    onClick={() =>
                      handleSendPrompt(
                        'Write a complete interactive Stopwatch with Start, Pause, Reset, and Lap buttons, formatted mm:ss:ms digital display, lap list, and sleek dark styling into index.html using write_file.'
                      )
                    }
                  >
                    Digital Stopwatch with Lap Tracker
                  </button>
                  <button
                    className="prompt-suggestion"
                    onClick={() => handleSendPrompt('Create a hello.py script that prints a greeting and system info, and run it')}
                  >
                    Create a hello.py and run it
                  </button>
                </div>
              </div>
            )}

            {/* Chronological Conversation & Tool Steps Timeline */}
            {timelineItems.map((item) => {
              if (item.kind === 'message') {
                const msg = item.msg;
                return (
                  <div key={msg.id} className="message-row">
                    {msg.sender === 'user' ? (
                      <div className="message-user">{msg.text}</div>
                    ) : (
                      <div className="message-agent">
                        <div className="agent-label">Assistant</div>
                        <div className="agent-text">{msg.text}</div>
                      </div>
                    )}
                  </div>
                );
              }

              const st = item.st;
              if (st.type === 'approval_required') {
                return (
                  <div key={st.id} className="approval-card">
                    <div className="approval-sentence">
                      Run: {st.data?.arguments?.command || st.data?.arguments?.path || st.data?.tool} ?
                    </div>
                    {st.data?.reason && (
                      <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                        {st.data.reason}
                      </div>
                    )}
                    {!st.data?.resolved ? (
                      <div className="approval-actions">
                        <button
                          className="btn-primary btn-sm"
                          onClick={() => handleApproval(st.data.approval_id, 'approve', false)}
                        >
                          Allow
                        </button>
                        <button
                          className="btn-secondary btn-sm"
                          onClick={() => handleApproval(st.data.approval_id, 'reject', false)}
                        >
                          Deny
                        </button>
                      </div>
                    ) : (
                      <div style={{ fontSize: '12px', color: st.data.resolved === 'approve' ? 'var(--status-green)' : 'var(--status-red)' }}>
                        {st.data.resolved === 'approve' ? 'Allowed' : 'Denied'}
                      </div>
                    )}
                  </div>
                );
              }

              const isExpanded = !!expandedSteps[st.id];

              return (
                <div key={st.id} className="step-row">
                  <div className="step-header" onClick={() => toggleStep(st.id)}>
                    <div className="step-title-group">
                      <span className={`step-chevron ${isExpanded ? 'expanded' : ''}`}>▶</span>
                      <span>{getStepTitle(st)}</span>
                    </div>
                    <span className="step-time">
                      {new Date(st.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>

                  {isExpanded && (
                    <div className="step-body">
                      {st.type === 'plan' && (
                        <ol style={{ paddingLeft: '16px' }}>
                          {st.data?.steps?.map((stepStr: string, idx: number) => (
                            <li key={idx} style={{ marginBottom: '4px' }}>
                              {stepStr}
                            </li>
                          ))}
                        </ol>
                      )}
                      {st.type === 'tool_call' && (
                        <pre style={{ margin: 0 }}>
                          {JSON.stringify(st.data?.arguments || {}, null, 2)}
                        </pre>
                      )}
                      {st.type === 'tool_result' && (
                        <pre style={{ margin: 0 }}>
                          {st.data?.output || JSON.stringify(st.data || {}, null, 2)}
                        </pre>
                      )}
                      {st.type === 'file_changed' && (
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span>{st.data?.path}</span>
                          <button
                            className="btn-secondary btn-sm"
                            onClick={() => {
                              setActiveDiff(st.data);
                              setActiveTab('diffs');
                            }}
                          >
                            View diff
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}

            {/* Active Security Approval Card if pending */}
            {activeApproval && !steps.some((s) => s.id === activeApproval.approval_id) && (
              <div className="approval-card">
                <div className="approval-sentence">
                  Run: {activeApproval.arguments?.command || activeApproval.arguments?.path || activeApproval.tool} ?
                </div>
                {activeApproval.reason && (
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    {activeApproval.reason}
                  </div>
                )}
                <div className="approval-actions">
                  <button
                    className="btn-primary btn-sm"
                    onClick={() => handleApproval(activeApproval.approval_id, 'approve', false)}
                  >
                    Allow
                  </button>
                  <button
                    className="btn-secondary btn-sm"
                    onClick={() => handleApproval(activeApproval.approval_id, 'reject', false)}
                  >
                    Deny
                  </button>
                </div>
              </div>
            )}

            {/* Live Streaming Token Output */}
            {isStreaming && streamingToken && (
              <div className="streaming-token-box">
                {streamingToken}
              </div>
            )}

            <div ref={chatEndRef} />
          </div>

          {/* Chat Input (Rule 10) */}
          <div className="chat-input-area">
            {showMentions && filteredMentionFiles.length > 0 && (
              <div className="mention-autocomplete">
                {filteredMentionFiles.slice(0, 6).map((p) => (
                  <div key={p} className="mention-item" onClick={() => handleSelectMention(p)}>
                    @{p}
                  </div>
                ))}
              </div>
            )}

            <div className="chat-input-box">
              <textarea
                className="chat-textarea"
                placeholder="Ask the assistant. Type @ to mention a file."
                value={inputPrompt}
                onChange={handleInputChange}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendPrompt(inputPrompt);
                  }
                }}
              />
              <div className="chat-input-footer">
                {isStreaming ? (
                  <button className="btn-secondary btn-sm" onClick={handleStop}>
                    Stop
                  </button>
                ) : (
                  <button
                    className="btn-primary btn-sm"
                    onClick={() => handleSendPrompt(inputPrompt)}
                    disabled={!inputPrompt.trim()}
                  >
                    Send
                  </button>
                )}
              </div>
            </div>
          </div>
        </aside>
      </div>
    </>
  );
}
