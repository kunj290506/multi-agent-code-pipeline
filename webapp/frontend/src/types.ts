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
  status: 'running' | 'success' | 'error' | 'cancelled'
  total_duration_ms: number | null
  steps: Step[]
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
