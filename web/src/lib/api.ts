// Thin fetch wrapper over the REST API. Same-origin in prod (FastAPI serves
// web/dist); the Vite dev proxy forwards /api -> :8000.
import type {
  AdminSettings,
  AdminUser,
  Job,
  User,
  UploadOptions,
  UsageSummary,
} from './types'

const BASE = '/api'

// Error thrown for any non-2xx response; carries the HTTP status so callers
// can branch on 401 (not authed) / 409 (conflict) etc.
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function parse(res: Response): Promise<any> {
  const ct = res.headers.get('content-type') || ''
  const body = ct.includes('application/json') ? await res.json() : await res.text()
  if (!res.ok) {
    const detail =
      typeof body === 'object' && body !== null && 'detail' in body
        ? (body as any).detail
        : body
    throw new ApiError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return body
}

// --- auth (cookie session) -------------------------------------------------

export async function me(): Promise<User> {
  const res = await fetch(`${BASE}/auth/me`)
  return parse(res)
}

export async function login(username: string, password: string): Promise<User> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  return parse(res)
}

export async function signup(username: string, password: string): Promise<{ username: string; pending: boolean }> {
  const res = await fetch(`${BASE}/auth/signup`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  return parse(res)
}

export async function logout(): Promise<void> {
  const res = await fetch(`${BASE}/auth/logout`, { method: 'POST' })
  await parse(res)
}

// --- my jobs ---------------------------------------------------------------

export async function deleteJob(id: string): Promise<{ deleted: boolean }> {
  const res = await fetch(`${BASE}/jobs/${id}`, { method: 'DELETE' })
  return parse(res)
}

export async function clearMyJobs(): Promise<{ deleted_jobs: number }> {
  const res = await fetch(`${BASE}/jobs/mine`, { method: 'DELETE' })
  return parse(res)
}

export async function clearAllJobs(): Promise<{ deleted_jobs: number }> {
  const res = await fetch(`${BASE}/jobs`, { method: 'DELETE' })
  return parse(res)
}

// --- admin ------------------------------------------------------------------

export async function adminUsers(): Promise<AdminUser[]> {
  const res = await fetch(`${BASE}/admin/users`)
  return parse(res)
}

export async function createAdminUser(
  username: string,
  password: string,
  is_admin?: boolean,
): Promise<AdminUser> {
  const res = await fetch(`${BASE}/admin/users`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ username, password, is_admin }),
  })
  return parse(res)
}

export async function patchAdminUser(
  username: string,
  patch: { is_admin?: boolean; status?: string; password?: string },
): Promise<AdminUser> {
  const res = await fetch(`${BASE}/admin/users/${encodeURIComponent(username)}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(patch),
  })
  return parse(res)
}

export async function deleteAdminUser(username: string): Promise<void> {
  const res = await fetch(`${BASE}/admin/users/${encodeURIComponent(username)}`, {
    method: 'DELETE',
  })
  await parse(res)
}

export async function adminJobs(): Promise<Job[]> {
  const res = await fetch(`${BASE}/admin/jobs`)
  return parse(res)
}

export async function usage(): Promise<UsageSummary> {
  const res = await fetch(`${BASE}/admin/usage`)
  return parse(res)
}

export async function adminSettings(): Promise<AdminSettings> {
  const res = await fetch(`${BASE}/admin/settings`)
  return parse(res)
}

export async function setAdminSettings(s: AdminSettings): Promise<AdminSettings> {
  const res = await fetch(`${BASE}/admin/settings`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(s),
  })
  return parse(res)
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

export interface SummaryTemplate {
  id: string
  label: string
}

export async function fetchSummaryTemplates(): Promise<SummaryTemplate[]> {
  const res = await fetch(`${BASE}/summary/templates`)
  return parse(res)
}

export interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
}

export async function summarizeJob(id: string, template: string | null): Promise<any> {
  const res = await fetch(`${BASE}/jobs/${id}/summarize`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ template }),
  })
  return parse(res)
}

export async function chatWithTranscript(
  id: string,
  message: string,
  history: ChatMsg[],
): Promise<string> {
  const res = await fetch(`${BASE}/jobs/${id}/chat`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ message, history: history.slice(-10) }),
  })
  const body = await parse(res)
  return body.reply as string
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
  if (opts.summary_template) fd.append('summary_template', opts.summary_template)
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
