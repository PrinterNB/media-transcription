import type { Job } from '../lib/types'

function statusColor(s: Job['status']): string {
  switch (s) {
    case 'done':
      return 'bg-emerald-500'
    case 'error':
      return 'bg-red-500'
    case 'cancelled':
      return 'bg-zinc-500'
    case 'running':
      return 'bg-amber-500'
    default:
      return 'bg-sky-500'
  }
}

export default function JobList({
  jobs,
  selectedId,
  onSelect,
  onNew,
  onClear,
}: {
  jobs: Job[]
  selectedId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onClear: () => void
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 flex gap-2">
        <button
          onClick={onNew}
          className="flex-1 rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm font-medium text-zinc-200 hover:border-zinc-700"
        >
          + New transcription
        </button>
        <button
          onClick={onClear}
          title="Clear job history and delete all inputs and outputs"
          className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-400 hover:border-red-900 hover:text-red-300"
        >
          Clear
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {jobs.length === 0 && (
          <p className="mt-4 text-center text-sm text-zinc-600">No jobs yet.</p>
        )}
        {jobs.map((j) => (
          <button
            key={j.id}
            onClick={() => onSelect(j.id)}
            className={`w-full rounded-lg border p-3 text-left transition ${
              j.id === selectedId
                ? 'border-emerald-700 bg-emerald-950/30'
                : 'border-zinc-800 bg-zinc-900/40 hover:border-zinc-700'
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm font-medium text-zinc-100">
                {j.source_name}
              </span>
              <span className={`h-2 w-2 shrink-0 rounded-full ${statusColor(j.status)}`} />
            </div>
            <div className="mt-1 flex items-center justify-between text-xs text-zinc-500">
              <span>{j.stage}</span>
              <span>
                {new Date(j.created_at + (j.created_at.endsWith('Z') ? 'Z' : '')).toLocaleString()}
              </span>
            </div>
            {(j.status === 'running' || j.status === 'queued') && (
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
                <div
                  className="h-full bg-amber-500 transition-all"
                  style={{ width: `${j.progress}%` }}
                />
              </div>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}
