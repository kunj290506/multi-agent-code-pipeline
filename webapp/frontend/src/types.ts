export interface Subtask {
  task_id: string
  agent: string
  description: string
  dependencies: string[]
  target_filename?: string
}

export interface Plan {
  feature_request: string
  subtasks: Subtask[]
  reasoning?: string
}

export interface Step {
  agent: string
  status: 'done' | 'failed' | 'cancelled' | 'running'
  attempt_number: number
  input_summary: string
  output_summary: string
  verdict: string | null
  severity_counts: Record<string, number>
  duration_ms: number | null
  data: Record<string, unknown>
}

export interface RunState {
  request_id: string
  feature_request: string
  started_at: string
  completed_at: string | null
  status: 'running' | 'success' | 'error' | 'cancelled' | 'awaiting_approval'
  total_duration_ms: number | null
  steps: Step[]
  plan?: Plan | null
}

export interface LogEntry {
  filename: string
  request_id: string
  feature_request: string
  overall_status: string
  total_duration_ms: number | null
  started_at: string
  completed_at: string | null
  retry_count: number
}

export interface FileNode {
  name: string
  type: 'file' | 'folder'
  path: string
  children?: FileNode[]
}

export interface Project {
  request_id: string
  project_name: string
  workspace_dir: string
  feature_request: string
  status: string
  file_count: number
  timestamp: number
}
