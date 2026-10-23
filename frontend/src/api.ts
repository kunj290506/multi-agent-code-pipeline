// frontend/src/api.ts
/**
 * REST API and SSE client for local agentic coding assistant backend (:8000).
 */

const API_BASE = typeof window !== 'undefined' && window.location.hostname
  ? `http://${window.location.hostname}:8000`
  : 'http://127.0.0.1:8000';

let cachedToken = '';
let tokenPromise: Promise<string> | null = null;

export async function getSessionToken(): Promise<string> {
  if (cachedToken) return cachedToken;
  if (!tokenPromise) {
    tokenPromise = (async () => {
      try {
        const res = await fetch(`${API_BASE}/auth/token`);
        if (res.ok) {
          const data = await res.json();
          cachedToken = data.token || '';
        }
      } catch (err) {
        console.error('Failed to fetch auth token:', err);
      } finally {
        tokenPromise = null;
      }
      return cachedToken;
    })();
  }
  return tokenPromise;
}

async function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const token = await getSessionToken();
  const headers = new Headers(options.headers || {});
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
    headers.set('X-Session-Token', token);
  }
  return fetch(url, { ...options, headers });
}

export async function loginUser(username: string, password: string): Promise<{ username: string; token: string }> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Invalid username or password');
  }
  const data = await res.json();
  cachedToken = data.token || '';
  return data;
}

export function clearAuthToken() {
  cachedToken = '';
  tokenPromise = null;
}

export function getPreviewUrl(subpath: string = ''): string {
  const base = typeof window !== 'undefined' && window.location.hostname
    ? `http://${window.location.hostname}:8000`
    : 'http://127.0.0.1:8000';
  return subpath ? `${base}/preview/${subpath.replace(/^\//, '')}` : `${base}/preview/`;
}

export interface Session {
  id: string;
  name: string;
  workspace_path: string;
  model: string;
  auto_approve_writes: boolean;
  created_at: number;
  updated_at: number;
}

export interface Message {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  metadata?: Record<string, any>;
  created_at: number;
}

export interface StepItem {
  id: string;
  type: 'plan' | 'tool_call' | 'approval_required' | 'tool_result' | 'file_changed' | 'terminal';
  title: string;
  data: any;
  timestamp: number;
  collapsed?: boolean;
}

export interface HealthStatus {
  status: string;
  services: {
    ollama: { status: string; models?: string[] };
    n8n: { status: string };
    database: { status: string };
    workspace: { status: string; path?: string };
  };
}

export interface FileTreeNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  size?: number;
  children?: FileTreeNode[];
}

export async function fetchHealth(): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health check returned ${res.status}`);
  return res.json();
}

export async function fetchModels(): Promise<string[]> {
  const res = await authFetch(`${API_BASE}/models`);
  if (!res.ok) return ['qwen2.5:7b-instruct-q4_K_M'];
  const data = await res.json();
  return data.models || ['qwen2.5:7b-instruct-q4_K_M'];
}

export async function listSessions(): Promise<Session[]> {
  const res = await authFetch(`${API_BASE}/sessions`);
  if (!res.ok) throw new Error('Failed to load sessions');
  const data = await res.json();
  return data.sessions || [];
}

export async function createSession(params: Partial<Session>): Promise<Session> {
  const res = await authFetch(`${API_BASE}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error('Failed to create session');
  return res.json();
}

export async function updateSession(sessionId: string, params: Partial<Session>): Promise<Session> {
  const res = await authFetch(`${API_BASE}/sessions/${sessionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error('Failed to update session');
  return res.json();
}

export async function deleteSession(sessionId: string): Promise<boolean> {
  const res = await authFetch(`${API_BASE}/sessions/${sessionId}`, { method: 'DELETE' });
  return res.ok;
}

export async function getSessionMessages(sessionId: string): Promise<Message[]> {
  const res = await authFetch(`${API_BASE}/sessions/${sessionId}/messages`);
  if (!res.ok) throw new Error('Failed to fetch messages');
  const data = await res.json();
  return data.messages || [];
}

export async function stopSessionTurn(sessionId: string): Promise<boolean> {
  const res = await authFetch(`${API_BASE}/sessions/${sessionId}/stop`, { method: 'POST' });
  return res.ok;
}

export async function resolveApproval(approvalId: string, action: 'approve' | 'reject', autoApproveAll: boolean = false): Promise<boolean> {
  const res = await authFetch(`${API_BASE}/approvals/${approvalId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, auto_approve_all: autoApproveAll }),
  });
  return res.ok;
}

export async function fetchFileTree(workspacePath?: string): Promise<FileTreeNode[]> {
  const url = workspacePath ? `${API_BASE}/files/tree?workspace_path=${encodeURIComponent(workspacePath)}` : `${API_BASE}/files/tree`;
  const res = await authFetch(url);
  if (!res.ok) return [];
  const data = await res.json();
  return data.tree || [];
}

export async function readFile(path: string, workspacePath?: string): Promise<string> {
  const url = `${API_BASE}/files?path=${encodeURIComponent(path)}` + (workspacePath ? `&workspace_path=${encodeURIComponent(workspacePath)}` : '');
  const res = await authFetch(url);
  if (!res.ok) throw new Error(`Could not read file ${path}`);
  const data = await res.json();
  return data.content || '';
}

export async function saveFile(path: string, content: string, workspacePath?: string): Promise<boolean> {
  const res = await authFetch(`${API_BASE}/files`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, content, workspace_path: workspacePath }),
  });
  return res.ok;
}

export async function undoFile(path: string, workspacePath?: string): Promise<{ success: boolean; restored_content?: string }> {
  const res = await authFetch(`${API_BASE}/files/undo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, workspace_path: workspacePath }),
  });
  if (!res.ok) return { success: false };
  return res.json();
}

export async function fetchAuditLogs(sessionId?: string): Promise<any[]> {
  const url = sessionId ? `${API_BASE}/audit?session_id=${encodeURIComponent(sessionId)}` : `${API_BASE}/audit`;
  const res = await authFetch(url);
  if (!res.ok) return [];
  const data = await res.json();
  return data.audit_logs || [];
}

/**
 * Connect to SSE endpoint for streaming agent responses and events.
 */
export function streamAgentTurn(
  sessionId: string,
  prompt: string,
  callbacks: {
    onToken?: (token: string) => void;
    onPlan?: (steps: string[]) => void;
    onToolCall?: (data: { name: string; arguments: any; id: string }) => void;
    onApprovalRequired?: (data: { approval_id: string; tool: string; arguments: any; reason: string }) => void;
    onToolResult?: (data: { name: string; id: string; success: boolean; output: string }) => void;
    onFileChanged?: (data: { path: string; before: string; after: string }) => void;
    onTerminal?: (data: { command: string; output: string; returncode: number }) => void;
    onError?: (error: string) => void;
    onDone?: (data: any) => void;
  }
): () => void {
  const controller = new AbortController();

  getSessionToken().then((token) => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
      headers['X-Session-Token'] = token;
    }

    fetch(`${API_BASE}/sessions/${sessionId}/messages`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ content: prompt }),
      signal: controller.signal,
    }).then(async (response) => {
      if (!response.ok || !response.body) {
        callbacks.onError?.(`Server responded with HTTP ${response.status}`);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';

        for (const part of parts) {
          if (!part.trim()) continue;
          const lines = part.split('\n');
          let eventType = 'message';
          let dataString = '';

          for (const line of lines) {
            if (line.startsWith('event:')) {
              eventType = line.replace('event:', '').trim();
            } else if (line.startsWith('data:')) {
              dataString = line.replace('data:', '').trim();
            }
          }

          if (!dataString) continue;

          try {
            const parsed = JSON.parse(dataString);
            switch (eventType) {
              case 'token':
                callbacks.onToken?.(parsed.token || '');
                break;
              case 'plan':
                callbacks.onPlan?.(parsed.steps || []);
                break;
              case 'tool_call':
                callbacks.onToolCall?.(parsed);
                break;
              case 'approval_required':
                callbacks.onApprovalRequired?.(parsed);
                break;
              case 'tool_result':
                callbacks.onToolResult?.(parsed);
                break;
              case 'file_changed':
                callbacks.onFileChanged?.(parsed);
                break;
              case 'terminal':
                callbacks.onTerminal?.(parsed);
                break;
              case 'error':
                callbacks.onError?.(parsed.message || 'Unknown error');
                break;
              case 'done':
                callbacks.onDone?.(parsed);
                break;
            }
          } catch {
            // ignore
          }
        }
      }
    }).catch((err) => {
      if (err.name !== 'AbortError') {
        callbacks.onError?.(err.message || 'Connection lost');
      }
    });
  });

  return () => {
    controller.abort();
  };
}
