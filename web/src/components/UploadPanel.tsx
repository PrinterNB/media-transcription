import { useRef, useState } from 'react'
import JobForm, { DEFAULT_FORM, type FormState } from './JobForm'
import { extractWav16k } from '../lib/extract'

interface Props {
  onSubmit: (
    blob: Blob,
    fileName: string,
    opts: FormState & { extracted: boolean },
  ) => Promise<void>
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  const u = ['KB', 'MB', 'GB']
  let i = -1
  do {
    n /= 1024
    i++
  } while (n >= 1024 && i < u.length - 1)
  return `${n.toFixed(n >= 100 ? 0 : 1)} ${u[i]}`
}

export default function UploadPanel({ onSubmit }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [form, setForm] = useState<FormState>(DEFAULT_FORM)
  const [busy, setBusy] = useState(false)
  const [phase, setPhase] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const pick = (f: File | null) => {
    setFile(f)
    setError(null)
  }

  const start = async () => {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      setPhase('Preparing audio…')
      const { blob, extracted } = await extractWav16k(file)
      setPhase('Uploading…')
      await onSubmit(blob, file.name, { ...form, extracted })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      setPhase(null)
    }
  }

  return (
    <div className="flex h-full flex-col gap-4">
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault()
          pick(e.dataTransfer.files?.[0] || null)
        }}
        className="rounded-xl border-2 border-dashed border-zinc-800 bg-zinc-900/40 p-6 text-center hover:border-zinc-700"
      >
        <input
          ref={inputRef}
          type="file"
          accept="audio/*,video/*,.mkv,.avi,.wmv"
          className="hidden"
          onChange={(e) => pick(e.target.files?.[0] || null)}
        />
        <p className="text-sm text-zinc-300">
          {file ? (
            <span className="text-zinc-100">
              {file.name} <span className="text-zinc-500">({fmtBytes(file.size)})</span>
            </span>
          ) : (
            'Drop an audio or video file, or'
          )}
        </p>
        {!file && (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="mt-3 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500"
          >
            Choose file
          </button>
        )}
        {file && (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="mt-3 text-sm text-zinc-400 hover:text-zinc-200"
          >
            change
          </button>
        )}
      </div>

      <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">
          Options
        </p>
        <JobForm value={form} onChange={setForm} />
      </div>

      <div className="mt-auto flex items-center gap-3">
        <button
          type="button"
          disabled={!file || busy}
          onClick={start}
          className="rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? phase || 'Working…' : 'Transcribe'}
        </button>
        {form.naming && !form.diarize && (
          <span className="text-xs text-amber-500">
            Naming needs “Separate speakers” on.
          </span>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-red-900/60 bg-red-950/40 p-3 text-sm text-red-300">
          {error}
        </div>
      )}
    </div>
  )
}
