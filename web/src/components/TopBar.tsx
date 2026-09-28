import type { User } from '../lib/types'
import type { View } from '../lib/types'

export default function TopBar({
  user,
  view,
  setView,
  onSignOut,
}: {
  user: User
  view: View
  setView: (v: View) => void
  onSignOut: () => void
}) {
  return (
    <header className="flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-zinc-800 px-4 py-2 sm:py-3">
      <h1 className="text-lg font-bold text-zinc-100">Transcription</h1>
      {/* Wraps to a second line below md so every control keeps a real tap target */}
      <div className="flex flex-wrap items-center gap-2">
        {user.is_admin && (
          <button
            onClick={() => setView(view === 'admin' ? 'jobs' : 'admin')}
            className={`inline-flex min-h-10 items-center justify-center rounded-lg border px-3 py-1.5 text-xs font-medium transition sm:min-h-0 ${
              view === 'admin'
                ? 'border-emerald-700 bg-emerald-950/40 text-emerald-300'
                : 'border-zinc-800 bg-zinc-900 text-zinc-300 hover:border-zinc-700'
            }`}
          >
            Admin panel
          </button>
        )}
        <span className="rounded-full bg-zinc-800 px-3 py-1 text-xs text-zinc-300">
          {user.username}
          {user.is_admin && <span className="ml-1 text-emerald-400">· admin</span>}
        </span>
        <button
          onClick={onSignOut}
          className="inline-flex min-h-10 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-300 hover:border-zinc-700 sm:min-h-0"
        >
          Sign out
        </button>
      </div>
    </header>
  )
}
