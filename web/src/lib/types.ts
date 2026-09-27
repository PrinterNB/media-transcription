// API mirror — keep in sync with server/app/db.py and routes.

export interface Word {
  text: string
  start: number
  end: number
}

export interface Segment {
  start: number
  end: number
  text: string
  speaker: string | null
  words?: Word[]
}

export interface SpeakerInfo {
  name: string | null
  confidence: number
  evidence: string
}

export type JobStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled'

export interface Job {
  id: string
  owner?: string
  source_name: string
  size_bytes: number
  status: JobStatus
  stage: string
  progress: number
  message?: string | null
  error?: string | null
  options: {
    asr: 'canary' | 'whisper'
    language_hint: string | null
    extracted: boolean
    diarize: boolean
    naming: boolean
    ollama_model?: string | null
    summary_template?: string | null
  }
  detected_language?: string | null
  speaker_map?: Record<string, SpeakerInfo>
  segments?: Segment[]
  output_paths?: Record<string, string>
  summaries?: Record<string, string>
  pending_summary?: string | null
  created_at: string
  finished_at?: string | null
}

export interface UploadOptions {
  asr: 'canary' | 'whisper'
  language_hint?: string
  extracted: boolean
  diarize: boolean
  naming: boolean
  ollama_model?: string
  summary_template?: string
}

export type UserStatus = 'active' | 'pending' | 'disabled'

export interface User {
  username: string
  is_admin: boolean
  status: UserStatus
  created_at: string
  last_login_at: string | null
}

export interface AdminUser {
  id: number
  username: string
  is_admin: boolean
  status: UserStatus
  created_at: string
  last_login_at: string | null
  job_count: number
  bytes: number
  prompt_tokens: number
  completion_tokens: number
}

export interface UsageUser {
  username: string
  is_admin: boolean
  jobs: number
  bytes: number
  prompt_tokens: number
  completion_tokens: number
  duration_sec: number
}

export interface UsageSummary {
  users: UsageUser[]
  totals: Record<string, number>
}

export interface AdminSettings {
  require_approval: boolean
}

// Main-view switch (there is no router: App swaps panes on this state).
export type View = 'jobs' | 'admin'
