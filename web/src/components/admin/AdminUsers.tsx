import { useCallback, useEffect, useState } from 'react'
import * as api from '../../lib/api'
import type { AdminUser } from '../../lib/types'
import { errMsg, fmtDate, fmtNum } from './format'

const inputCls =
  'rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-100 outline-none focus:border-emerald-600'

const btn =
  'rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1 text-xs text-zinc-300 hover:border-zinc-700'

function statusBadge(status: AdminUser['status']) {
  const cls =
    status === 'active'
      ? 'bg-emerald-950/60 text-emerald-300'
      : status === 'pending'
        ? 'bg-amber-950/60 text-amber-300'
        : 'bg-zinc-800 text-zinc-400'
  return <span className={`rounded-full px-2 py-0.5 text-xs ${cls}`}>{status}</span>
}

export default function AdminUsers({ me }: { me: string }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  // Add-user form
  const [nuName, setNuName] = useState('')
  const [nuPass, setNuPass] = useState('')
  const [nuAdmin, setNuAdmin] = useState(false)

  // Per-row "set password" (username of the open row)
  const [pwUser, setPwUser] = useState<string | null>(null)
  const [pwValue, setPwValue] = useState('')

  const load = useCallback(async () => {
    try {
      setUsers(await api.adminUsers())
      setError(null)
    } catch (e) {
      setError(errMsg(e))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // Run an action, then re-list; surface failures (409 etc.) inline.
  const run = useCallback(
    async (fn: () => Promise<unknown>, ok?: string) => {
      setError(null)
      setNotice(null)
      try {
        await fn()
        if (ok) setNotice(ok)
        await load()
      } catch (e) {
        setError(errMsg(e))
      }
    },
    [load],
  )

  const addUser = () =>
    run(async () => {
      await api.createAdminUser(nuName, nuPass, nuAdmin)
      setNuName('')
      setNuPass('')
      setNuAdmin(false)
    }, 'User created.')

  const patch = (u: AdminUser, p: Partial<{ is_admin: boolean; status: string }>) =>
    run(() => api.patchAdminUser(u.username, p))

  const del = (u: AdminUser) =>
    run(
      () => api.deleteAdminUser(u.username),
      `Deleted ${u.username} (and their jobs).`,
    )

  const openPw = (u: AdminUser) => {
    setPwUser(pwUser === u.username ? null : u.username)
    setPwValue('')
  }

  const savePw = (u: AdminUser) =>
    run(() => api.patchAdminUser(u.username, { password: pwValue }), `Password updated for ${u.username}.`)

  return (
    <div className="space-y-4">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (!nuName || !nuPass) return
          void addUser()
        }}
        className="flex flex-wrap items-end gap-2 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4"
      >
        <div className="flex-1 min-w-40">
          <p className="mb-1 text-xs font-medium text-zinc-400">Username</p>
          <input value={nuName} onChange={(e) => setNuName(e.target.value)} className={`w-full ${inputCls}`} />
        </div>
        <div className="flex-1 min-w-40">
          <p className="mb-1 text-xs font-medium text-zinc-400">Password</p>
          <input
            type="password"
            value={nuPass}
            onChange={(e) => setNuPass(e.target.value)}
            className={`w-full ${inputCls}`}
          />
        </div>
        <label className="flex items-center gap-2 pb-2 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={nuAdmin}
            onChange={(e) => setNuAdmin(e.target.checked)}
            className="accent-emerald-500"
          />
          Admin
        </label>
        <button
          type="submit"
          disabled={!nuName || !nuPass}
          className="rounded-lg bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Add user
        </button>
      </form>

      {notice && (
        <div className="rounded-lg border border-emerald-900/60 bg-emerald-950/40 p-3 text-sm text-emerald-300">
          {notice}
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-red-900/60 bg-red-950/40 p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border border-zinc-800">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-xs uppercase tracking-wide text-zinc-500">
              <th className="px-3 py-2 font-medium">User</th>
              <th className="px-3 py-2 font-medium">Role</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Created</th>
              <th className="px-3 py-2 font-medium">Last login</th>
              <th className="px-3 py-2 text-right font-medium">Jobs</th>
              <th className="px-3 py-2 text-right font-medium">Tokens (in/out)</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {(users ?? []).map((u) => {
              const isMe = u.username === me
              const editing = pwUser === u.username
              return [
                <tr key={u.username} className="border-b border-zinc-800/60 align-top">
                  <td className="px-3 py-2 font-medium text-zinc-100">
                    {u.username}
                    {isMe && <span className="ml-1 text-xs text-zinc-500">(you)</span>}
                  </td>
                  <td className="px-3 py-2">
                    <button onClick={() => patch(u, { is_admin: !u.is_admin })} className={btn} title="Toggle admin">
                      {u.is_admin ? 'Admin' : 'User'}
                    </button>
                  </td>
                  <td className="px-3 py-2">{statusBadge(u.status)}</td>
                  <td className="px-3 py-2 text-zinc-400">{fmtDate(u.created_at)}</td>
                  <td className="px-3 py-2 text-zinc-400">{fmtDate(u.last_login_at)}</td>
                  <td className="px-3 py-2 text-right text-zinc-400">{u.job_count}</td>
                  <td className="px-3 py-2 text-right text-zinc-400">
                    {fmtNum(u.prompt_tokens)} / {fmtNum(u.completion_tokens)}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap justify-end gap-1">
                      {u.status === 'pending' && (
                        <button onClick={() => patch(u, { status: 'active' })} className={btn}>
                          Approve
                        </button>
                      )}
                      {u.status === 'active' && (
                        <button onClick={() => patch(u, { status: 'disabled' })} className={btn}>
                          Disable
                        </button>
                      )}
                      {u.status === 'disabled' && (
                        <button onClick={() => patch(u, { status: 'active' })} className={btn}>
                          Enable
                        </button>
                      )}
                      <button onClick={() => openPw(u)} className={btn}>
                        {isMe ? 'Change password' : 'Set password'}
                      </button>
                      <button
                        onClick={() => {
                          if (window.confirm(`Delete ${u.username}? Their jobs and files will be deleted too.`)) {
                            void del(u)
                          }
                        }}
                        className="rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1 text-xs text-red-400 hover:border-red-900"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>,
                editing && (
                  <tr key={`${u.username}-pw`} className="border-b border-zinc-800/60 bg-zinc-950/40">
                    <td />
                    <td colSpan={7} className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-zinc-400">New password for {u.username}:</span>
                        <input
                          type="password"
                          value={pwValue}
                          onChange={(e) => setPwValue(e.target.value)}
                          placeholder="min 8 characters"
                          className={inputCls}
                        />
                        <button
                          onClick={() => void savePw(u)}
                          disabled={!pwValue}
                          className="rounded-lg bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
                        >
                          Save
                        </button>
                        <button onClick={() => setPwUser(null)} className={btn}>
                          Cancel
                        </button>
                      </div>
                    </td>
                  </tr>
                ),
              ]
            })}
            {users && users.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-4 text-center text-zinc-600">
                  No users.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-zinc-600">
        Deleting a user also deletes their jobs and files. A user with a running job can't be deleted
        yet.
      </p>
    </div>
  )
}
