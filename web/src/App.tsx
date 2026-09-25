import { useState } from 'react'
import { useJobs } from './hooks/useJobs'
import JobList from './components/JobList'
import type { FormState } from './components/JobForm'
import TranscriptView from './components/TranscriptView'
import DownloadBar from './components/DownloadBar'
import UploadPanel from './components/UploadPanel'
import type { Job } from './lib/types'

function ProgressCard({ job }: { job: Job }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-zinc-200">
          {job.status === 'queued' ? 'Queued…' : job.stage}
        </span>
        <span className="font-mono text-xs text-zinc-500">{job.progress}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-800">
        <div
          className="h-full bg-emerald-500 transition-all"
          style={{ width: `${job.progress}%` }}
        />
      </div>
      {job.message && (
        <p className="mt-2 truncate text-xs text-zinc-500">{job.message}</p>
      )}
    </div>
  )
}

function DetailPane({
  job,
  onCancel,
}: {
  job: Job
  onCancel: (id: string) => void
}) {
  const running = job.status === 'running' || job.status === 'queued'
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-zinc-100">
            {job.source_name}
          </h2>
          <p className="mt-0.5 text-xs text-zinc-500">
            {job.status} · {job.options.asr === 'canary' ? 'Canary (English)' : 'Whisper (multilingual)'}
            {job.options.ollama_model ? ` · naming: ${job.options.ollama_model}` : ''}
            {job.detected_language ? ` · detected ${job.detected_language}` : ''}
          </p>
        </div>
        {running && (
          <button
            onClick={() => onCancel(job.id)}
            className="rounded-lg border border-red-900/60 px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-950/40"
          >
            Cancel
          </button>
        )}
      </div>

      {job.status === 'error' && (
        <div className="m-4 rounded-lg border border-red-900/60 bg-red-950/40 p-3 text-sm text-red-300">
          {job.error}
        </div>
      )}
      {job.status === 'cancelled' && (
        <div className="m-4 rounded-lg border border-zinc-800 bg-zinc-900/60 p-3 text-sm text-zinc-400">
          Cancelled.
        </div>
      )}
      {running && (
        <div className="m-4">
          <ProgressCard job={job} />
        </div>
      )}

      {job.status === 'done' && (
        <>
          <DownloadBar job={job} />
          <div className="min-h-0 flex-1 overflow-y-auto py-2">
            <TranscriptView job={job} />
          </div>
        </>
      )}
    </div>
  )
}

export default function App() {
  const { jobs, selected, selectedId, select, submitJob, cancel, health } = useJobs()
  const [creating, setCreating] = useState(jobs.length > 0 ? false : true)

  const openNew = () => setCreating(true)
  const openJob = (id: string) => {
    setCreating(false)
    select(id)
  }

  return (
    <div className="flex h-full">
      <aside className="flex w-80 shrink-0 flex-col border-r border-zinc-800 p-3">
        <h1 className="mb-3 px-1 text-lg font-bold text-zinc-100">Transcription</h1>
        <JobList jobs={jobs} selectedId={creating ? null : selectedId} onSelect={openJob} onNew={openNew} />
        <footer className="mt-3 px-1 text-[11px] leading-4 text-zinc-600">
          {health ? (
            <>
              ffmpeg {health.ffmpeg ? '✓' : '✗ missing'} · Ollama{' '}
              {health.ollama_reachable ? '✓' : '✗ offline'}
            </>
          ) : (
            'connecting…'
          )}
        </footer>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        {creating ? (
          <div className="flex h-full overflow-y-auto p-4">
            <div className="mx-auto w-full max-w-md">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">
                New transcription
              </h2>
              <UploadPanel
                onSubmit={async (blob, name, form: FormState & { extracted: boolean }) => {
                  await submitJob(blob, name, form)
                  setCreating(false)
                }}
              />
            </div>
          </div>
        ) : selected ? (
          <DetailPane job={selected} onCancel={cancel} />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-zinc-600">
            Select a job, or start a new transcription.
          </div>
        )}
      </main>
    </div>
  )
}
