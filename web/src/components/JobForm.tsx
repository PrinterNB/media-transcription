// Controls for a new transcription: ASR backend dropdown + feature toggles.
// `extracted` is decided automatically at upload time (see UploadPanel).

export interface FormState {
  asr: 'canary' | 'whisper'
  language_hint: string
  diarize: boolean
  naming: boolean
  ollama_model: string
  summary_template: string
}

export const DEFAULT_FORM: FormState = {
  asr: 'canary',
  language_hint: '',
  diarize: true,
  naming: true,
  ollama_model: '',
  summary_template: '',
}

import { useEffect, useState, type ReactNode } from 'react'
import { fetchOllamaModels, fetchSummaryTemplates, type SummaryTemplate } from '../lib/api'

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="flex items-baseline justify-between">
        <span className="text-sm font-medium text-zinc-200">{label}</span>
        {hint && <span className="text-xs text-zinc-500">{hint}</span>}
      </span>
      {children}
    </label>
  )
}

function Toggle({ on, onChange, label, hint }: { on: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!on)}
      className="flex w-full items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2 text-left hover:border-zinc-700"
    >
      <span>
        <span className="text-sm font-medium text-zinc-200">{label}</span>
        {hint && <span className="ml-2 text-xs text-zinc-500">{hint}</span>}
      </span>
      <span
        className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition ${
          on ? 'bg-emerald-500' : 'bg-zinc-700'
        }`}
      >
        <span
          className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
            on ? 'translate-x-4' : 'translate-x-0'
          }`}
        />
      </span>
    </button>
  )
}

export default function JobForm({
  value,
  onChange,
}: {
  value: FormState
  onChange: (v: FormState) => void
}) {
  const set = (patch: Partial<FormState>) => onChange({ ...value, ...patch })
  // null = still loading; [] = Ollama up but empty (treated as unreachable)
  const [models, setModels] = useState<string[] | null>(null)
  const [templates, setTemplates] = useState<SummaryTemplate[]>([])
  useEffect(() => {
    let alive = true
    fetchOllamaModels()
      .then((r) => alive && setModels(r.models || []))
      .catch(() => alive && setModels([]))
    fetchSummaryTemplates()
      .then((t) => alive && setTemplates(t))
      .catch(() => alive && setTemplates([]))
    return () => {
      alive = false
    }
  }, [])
  return (
    <div className="space-y-3">
      <Field label="Transcription model" hint={value.asr === 'canary' ? 'English + accents' : 'all languages'}>
        <select
          value={value.asr}
          onChange={(e) => set({ asr: e.target.value as 'canary' | 'whisper' })}
          className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-emerald-600"
        >
          <option value="canary">English (recommended whenever possible)</option>
          <option value="whisper">Not only English (only when necessary)</option>
        </select>
      </Field>

      {value.asr === 'whisper' && (
        <Field label="Language hint (optional)" hint="leave blank to auto-detect">
          <input
            type="text"
            value={value.language_hint}
            onChange={(e) => set({ language_hint: e.target.value })}
            placeholder="e.g. Spanish, Japanese, en"
            className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-emerald-600"
          />
        </Field>
      )}

      <div className="space-y-2 pt-1">
        <Toggle
          on={value.diarize}
          onChange={(v) => set({ diarize: v })}
          label="Separate speakers"
          hint="pyannote diarization"
        />
        <Toggle
          on={value.naming}
          onChange={(v) => set({ naming: v })}
          label="Name speakers"
          hint="needs separation on"
        />
        <Field label="Ollama model" hint="naming stage">
          <select
            value={value.ollama_model}
            onChange={(e) => set({ ollama_model: e.target.value })}
            className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-emerald-600"
          >
            {models === null ? (
              <option value="">(default)</option>
            ) : models.length === 0 ? (
              <option value="" disabled>(default — Ollama unreachable)</option>
            ) : (
              <>
                <option value="">(default)</option>
                {models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </>
            )}
          </select>
        </Field>
        <Field label="Summary" hint="runs when transcription finishes">
          <select
            value={value.summary_template}
            onChange={(e) => set({ summary_template: e.target.value })}
            className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-emerald-600"
          >
            <option value="">None (ask after it's done)</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </Field>
      </div>
    </div>
  )
}
