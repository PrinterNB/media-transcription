import { useCallback, useState } from 'react'
import { useSession } from './hooks/useSession'
import { useJobs } from './hooks/useJobs'
import { useIsMobile } from './hooks/useIsMobile'
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

// ← tap target for the phone trees only (detail / new-job screens).
function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-label="Back"
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 text-lg leading-none text-zinc-200 hover:border-zinc-700"
    >
      ←
    </button>
  )
}

function DetailPane({
  job,
  onCancel,
  onDelete,
  onBack,
}: {
  job: Job
  onCancel: (id: string) => void
  onDelete: (id: string) => void
  // Phone-only: renders a ← button left of the title. Omitted on desktop.
  onBack?: () => void
}) {
  const running = job.status === 'running' || job.status === 'queued'
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-zinc-800 px-4 py-2 sm:py-3">
        {onBack && <BackButton onClick={onBack} />}
        <div className="min-w-0 flex-1 sm:flex-none">
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
              className="rounded-lg border border-red-900/60 px-3 py-2 text-xs font-medium text-red-400 hover:bg-red-950/40 sm:py-1.5"
            >
              Cancel
            </button>
          )}
          {!running && (
            <button
              onClick={() => onDelete(job.id)}
              title="Delete this job and its files"
              className="rounded-lg border border-zinc-800 px-3 py-2 text-xs font-medium text-zinc-400 hover:border-red-900 hover:text-red-300 sm:py-1.5"
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

function HealthFooter({ health }: { health: { ffmpeg: boolean; ollama_reachable: boolean } | null }) {
  return (
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
  )
}

export default function App() {
  const { user, loading, refresh, signOut } = useSession()
  const [view, setView] = useState<View>('jobs')
  const isMobile = useIsMobile()

  // Phone-only navigation: the phone shows ONE screen at a time — the job
  // list (home), a job detail, or the new-job form. The md+ tree ignores
  // this state entirely and keeps the two-pane layout.
  const [phoneScreen, setPhoneScreen] = useState<'list' | 'detail' | 'new'>('list')

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

  // Phone wrappers: same actions as above, plus push the phone to that screen.
  const phoneOpenJob = (id: string) => {
    openJob(id)
    setPhoneScreen('detail')
  }
  const phoneOpenNew = () => {
    openNew()
    setPhoneScreen('new')
  }
  const phoneBackToList = () => setPhoneScreen('list')

  const phoneUploadSubmit = async (
    blob: Blob,
    name: string,
    form: FormState & { extracted: boolean },
  ) => {
    await submitJob(blob, name, form)
    setCreating(false)
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

  // ---- Phone: single screen at a time ------------------------------------
  if (isMobile) {
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
        {view === 'admin' && user.is_admin ? (
          <div className="min-w-0 flex-1">
            <AdminPanel me={user} />
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col">
            {phoneScreen === 'list' ? (
              <div className="flex min-h-0 flex-1 flex-col p-3">
                <JobList
                  jobs={jobs}
                  selectedId={creating ? null : selectedId}
                  onSelect={phoneOpenJob}
                  onNew={phoneOpenNew}
                  onClear={clearHistory}
                />
                <HealthFooter health={health} />
              </div>
            ) : phoneScreen === 'new' ? (
              creating ? (
                <div className="flex min-h-0 flex-1 flex-col">
                  <div className="flex shrink-0 items-center gap-2 border-b border-zinc-800 px-3 py-2">
                    <BackButton onClick={phoneBackToList} />
                    <h2 className="text-sm font-semibold text-zinc-100">
                      New transcription
                    </h2>
                  </div>
                  <div className="min-h-0 flex-1 overflow-y-auto p-4">
                    <div className="w-full max-w-md">
                      <UploadPanel onSubmit={phoneUploadSubmit} />
                    </div>
                  </div>
                </div>
              ) : selected ? (
                // Just submitted: the new job is selected — show its detail.
                <DetailPane
                  job={selected}
                  onCancel={cancel}
                  onDelete={deleteJob}
                  onBack={phoneBackToList}
                />
              ) : (
                <div className="flex min-h-0 flex-1 items-center justify-center p-4 text-center text-sm text-zinc-600">
                  Select a job, or start a new transcription.
                </div>
              )
            ) : selected ? (
              <DetailPane
                job={selected}
                onCancel={cancel}
                onDelete={deleteJob}
                onBack={phoneBackToList}
              />
            ) : (
              <div className="flex min-h-0 flex-1 items-center justify-center p-4 text-center text-sm text-zinc-600">
                Select a job, or start a new transcription.
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  // ---- Desktop (md+): two panes, unchanged --------------------------------
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
              <HealthFooter health={health} />
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
