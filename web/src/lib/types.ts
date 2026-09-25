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
  }
  detected_language?: string | null
  speaker_map?: Record<string, SpeakerInfo>
  segments?: Segment[]
  output_paths?: Record<string, string>
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
}
