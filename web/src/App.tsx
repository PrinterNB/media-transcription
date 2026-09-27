import { useCallback, useState } from 'react'
import { useSession } from './hooks/useSession'
import { useJobs } from './hooks/useJobs'
import JobList from './components/JobList'
import TopBar from './components/TopBar'
import AuthScreen from './components/AuthScreen'
import AdminPanel from './components/admin/AdminPanel'
import type { FormState } from './components/JobForm'
import TranscriptView from './components/TranscriptView'
import DownloadBar from './components/DownloadBar'
import SummaryPanel from './components/SummaryPanel'
import UploadPanel from './components/UploadPanel'
import type { Job, View } from './lib/types'

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
  onDelete,
}: {
  job: Job
  onCancel: (id: string) => void
  onDelete: (id: string) => void
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
        <div className="flex shrink-0 gap-2">
          {running && (
            <button
              onClick={() => onCancel(job.id)}
              className="rounded-lg border border-red-900/60 px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-950/40"
            >
              Cancel
            </button>
          )}
          {!running && (
            <button
              onClick={() => onDelete(job.id)}
              title="Delete this job and its files"
              className="rounded-lg border border-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-400 hover:border-red-900 hover:text-red-300"
            >
              Delete
            </button>
          )}
        </div>
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

      {job.status === 'done' && <DownloadBar job={job} />}

      <SummaryPanel job={job} />

      {job.status === 'done' && (
        <div className="min-h-0 flex-1 overflow-y-auto py-2">
          <TranscriptView job={job} />
        </div>
      )}
    </div>
  )
}

export default function App() {
  const { user, loading, refresh, signOut } = useSession()
  const [view, setView] = useState<View>('jobs')

  // Session was lost (401 from the jobs poll). No-op while already logged out
  // so the pre-login polling loop doesn't fire logout calls forever.
  const handleAuthLost = useCallback(() => {
    if (user) {
      setView('jobs')
      void signOut()
    }
  }, [user, signOut])

  const { jobs, selected, selectedId, select, submitJob, cancel, clearHistory, deleteJob, health } =
    useJobs(handleAuthLost)
  const [creating, setCreating] = useState(jobs.length > 0 ? false : true)

  const openNew = () => setCreating(true)
  const openJob = (id: string) => {
    setCreating(false)
    select(id)
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-zinc-700 border-t-emerald-500" />
      </div>
    )
  }

  if (!user) {
    return <AuthScreen onLoggedIn={refresh} />
  }

  return (
    <div className="flex h-full flex-col">
      <TopBar
        user={user}
        view={view}
        setView={setView}
        onSignOut={() => {
          setView('jobs')
          void signOut()
        }}
      />
      <div className="flex min-h-0 flex-1">
        {view === 'admin' && user.is_admin ? (
          <div className="min-w-0 flex-1">
            <AdminPanel me={user} />
          </div>
        ) : (
          <>
            <aside className="flex w-80 shrink-0 flex-col border-r border-zinc-800 p-3">
              <JobList
                jobs={jobs}
                selectedId={creating ? null : selectedId}
                onSelect={openJob}
                onNew={openNew}
                onClear={clearHistory}
              />
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
                <DetailPane job={selected} onCancel={cancel} onDelete={deleteJob} />
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-zinc-600">
                  Select a job, or start a new transcription.
                </div>
              )}
            </main>
          </>
        )}
      </div>
    </div>
  )
}
