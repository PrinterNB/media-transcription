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
    <header className="flex shrink-0 items-center justify-between border-b border-zinc-800 px-4 py-3">
      <h1 className="text-lg font-bold text-zinc-100">Transcription</h1>
      <div className="flex items-center gap-2">
        {user.is_admin && (
          <button
            onClick={() => setView(view === 'admin' ? 'jobs' : 'admin')}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
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
          className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-300 hover:border-zinc-700"
        >
          Sign out
        </button>
      </div>
    </header>
  )
}
