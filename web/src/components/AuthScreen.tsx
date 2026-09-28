import { useState } from 'react'
import * as api from '../lib/api'

const inputCls =
  'w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-base text-zinc-100 outline-none focus:border-emerald-600 sm:text-sm'

export default function AuthScreen({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [mode, setMode] = useState<'login' | 'signup'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)

  const fail = (e: unknown) => {
    setError(e instanceof Error ? e.message : String(e))
    setInfo(null)
  }

  const signIn = async () => {
    if (!username || !password) return
    setBusy(true)
    setError(null)
    setInfo(null)
    try {
      await api.login(username, password)
      onLoggedIn()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const signUp = async () => {
    if (!username || !password) return
    setBusy(true)
    setError(null)
    setInfo(null)
    try {
      const r = await api.signup(username, password)
      if (r.pending) {
        setInfo('Account created — waiting for admin approval.')
      } else {
        onLoggedIn()
      }
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center overflow-y-auto p-4 sm:p-6">
      <div className="w-full max-w-sm rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 sm:p-6">
        <h1 className="text-lg font-bold text-zinc-100">Transcription</h1>

        <div className="mt-4 space-y-3">
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Username"
            autoComplete="username"
            className={inputCls}
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && (mode === 'login' ? signIn() : signUp())}
            placeholder="Password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            className={inputCls}
          />
          {mode === 'login' ? (
            <button
              onClick={signIn}
              disabled={busy || !username || !password}
              className="w-full rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          ) : (
            <>
              <p className="text-xs text-zinc-500">
                An admin may need to approve your account.
              </p>
              <button
                onClick={signUp}
                disabled={busy || !username || !password}
                className="w-full rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {busy ? 'Creating…' : 'Create account'}
              </button>
            </>
          )}
        </div>

        {error && (
          <div className="mt-4 rounded-lg border border-red-900/60 bg-red-950/40 p-3 text-sm text-red-300">
            {error}
          </div>
        )}
        {info && (
          <div className="mt-4 rounded-lg border border-emerald-900/60 bg-emerald-950/40 p-3 text-sm text-emerald-300">
            {info}
          </div>
        )}

        <div className="my-4 flex items-center gap-3">
          <div className="h-px flex-1 bg-zinc-800" />
          <button
            onClick={() => {
              setMode(mode === 'login' ? 'signup' : 'login')
              setError(null)
              setInfo(null)
            }}
            className="text-sm text-zinc-400 hover:text-zinc-200"
          >
            {mode === 'login' ? '+ Add user' : '← Sign in instead'}
          </button>
          <div className="h-px flex-1 bg-zinc-800" />
        </div>
      </div>
    </div>
  )
}
