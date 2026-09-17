import type { RunState, LogEntry, FileNode } from './types'

export const BASE = 'http://localhost:8020'

export interface AuthUser {
  id: number
  username: string
}

async function checkResponse(res: Response): Promise<unknown> {
  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) message = body.detail
    } catch {
      // ignore parse error
    }
    throw new Error(message)
  }
  return res.json()
}

export async function authSignup(
  username: string,
  email: string,
  password: string,
): Promise<AuthUser> {
  const res = await fetch(`${BASE}/auth/signup`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password }),
  })
  return checkResponse(res) as Promise<AuthUser>
}

export async function authLogin(username: string, password: string): Promise<AuthUser> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  return checkResponse(res) as Promise<AuthUser>
}

export async function authMe(): Promise<AuthUser | null> {
  const res = await fetch(`${BASE}/auth/me`, { credentials: 'include' })
  if (res.status === 401) return null
  return checkResponse(res) as Promise<AuthUser>
}

export async function authLogout(): Promise<void> {
  await fetch(`${BASE}/auth/logout`, { method: 'POST', credentials: 'include' })
}

export async function startRun(request: string, projectName?: string): Promise<{ request_id: string }> {
  const body: Record<string, string> = { request }
  if (projectName) body.project_name = projectName
  const res = await fetch(`${BASE}/runs`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return checkResponse(res) as Promise<{ request_id: string }>
}

export async function getRunStatus(runId: string): Promise<RunState> {
  const res = await fetch(`${BASE}/runs/${runId}/status`, { credentials: 'include' })
  return checkResponse(res) as Promise<RunState>
}

export async function cancelRun(runId: string): Promise<void> {
  await fetch(`${BASE}/runs/${runId}/cancel`, { method: 'POST', credentials: 'include' })
}

export async function getLogs(): Promise<LogEntry[]> {
  const res = await fetch(`${BASE}/logs`, { credentials: 'include' })
  return checkResponse(res) as Promise<LogEntry[]>
}

export async function getFiles(projectId?: string): Promise<FileNode> {
  const url = projectId ? `${BASE}/files?project_id=${encodeURIComponent(projectId)}` : `${BASE}/files`
  const res = await fetch(url, { credentials: 'include' })
  return checkResponse(res) as Promise<FileNode>
}

export async function getFileContent(path: string): Promise<string> {
  const res = await fetch(`${BASE}/file?path=${encodeURIComponent(path)}`, { credentials: 'include' })
  const data = await checkResponse(res) as { content: string }
  return data.content
}

export async function runProject(
  projectId: string,
): Promise<{ runnable: boolean; url: string | null; port: number | null; type: string; reason: string | null }> {
  const res = await fetch(`${BASE}/projects/${projectId}/run`, {
    method: 'POST',
    credentials: 'include',
  })
  return checkResponse(res) as ReturnType<typeof runProject>
}
