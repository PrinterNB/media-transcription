// Thin fetch wrapper over the REST API. Same-origin in prod (FastAPI serves
// web/dist); the Vite dev proxy forwards /api -> :8000.
import type { Job, UploadOptions } from './types'

const BASE = '/api'

async function parse(res: Response): Promise<any> {
  const ct = res.headers.get('content-type') || ''
  const body = ct.includes('application/json') ? await res.json() : await res.text()
  if (!res.ok) {
    const detail =
      typeof body === 'object' && body !== null && 'detail' in body
        ? (body as any).detail
        : body
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return body
}

export async function listJobs(): Promise<Job[]> {
  const res = await fetch(`${BASE}/jobs`)
  return parse(res)
}

export interface OllamaModels {
  models: string[]
  error?: string
}

export async function fetchOllamaModels(): Promise<OllamaModels> {
  const res = await fetch(`${BASE}/ollama/models`)
  return parse(res)
}

export async function fetchHealth(): Promise<any> {
  const res = await fetch(`${BASE}/health`)
  return parse(res)
}

export async function getJob(id: string): Promise<Job> {
  const res = await fetch(`${BASE}/jobs/${id}`)
  return parse(res)
}

export async function cancelJob(id: string): Promise<Job> {
  const res = await fetch(`${BASE}/jobs/${id}/cancel`, { method: 'POST' })
  return parse(res)
}

export async function clearJobs(): Promise<{ deleted_jobs: number }> {
  const res = await fetch(`${BASE}/jobs`, { method: 'DELETE' })
  return parse(res)
}

export async function createJob(file: Blob, fileName: string, opts: UploadOptions): Promise<Job> {
  const fd = new FormData()
  // name it so the server keeps the original basename for display
  fd.append('file', file, fileName)
  fd.append('asr', opts.asr)
  if (opts.language_hint) fd.append('language_hint', opts.language_hint)
  fd.append('extracted', String(opts.extracted))
  fd.append('diarize', String(opts.diarize))
  fd.append('naming', String(opts.naming))
  if (opts.ollama_model) fd.append('ollama_model', opts.ollama_model)
  const res = await fetch(`${BASE}/jobs`, { method: 'POST', body: fd })
  return parse(res)
}

export function downloadUrl(id: string, fmt: 'txt' | 'srt' | 'vtt' | 'json'): string {
  return `${BASE}/jobs/${id}/download?fmt=${fmt}`
}

// Open an EventSource for a job's live updates. Returns a close function.
export function subscribeJob(id: string, onSnapshot: (job: Job) => void): () => void {
  const es = new EventSource(`${BASE}/jobs/${id}/events`)
  const onJobUpdate = (e: MessageEvent) => {
    try {
      onSnapshot(JSON.parse(e.data))
    } catch {
      /* ignore malformed */
    }
  }
  es.addEventListener('job_update', onJobUpdate)
  return () => es.close()
}
