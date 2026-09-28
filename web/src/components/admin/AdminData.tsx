import { useCallback, useEffect, useState } from 'react'
import * as api from '../../lib/api'
import type { AdminSettings, Job } from '../../lib/types'
import { errMsg, fmtDate } from './format'

const statusCls: Record<Job['status'], string> = {
  done: 'text-emerald-400',
  error: 'text-red-400',
  cancelled: 'text-zinc-500',
  running: 'text-amber-400',
  queued: 'text-sky-400',
}

export default function AdminData() {
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [settings, setSettings] = useState<AdminSettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const [j, s] = await Promise.all([api.adminJobs(), api.adminSettings()])
      setJobs(j)
      setSettings(s)
      setError(null)
    } catch (e) {
      setError(errMsg(e))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const toggleApproval = async (v: boolean) => {
    if (!settings) return
    const prev = settings
    setSettings({ ...settings, require_approval: v })
    try {
      setSettings(await api.setAdminSettings({ require_approval: v }))
    } catch (e) {
      setSettings(prev)
      setError(errMsg(e))
    }
  }

  const deleteJob = async (id: string) => {
    try {
      await api.deleteJob(id)
      await load()
    } catch (e) {
      setError(errMsg(e))
    }
  }

  const deleteAll = async () => {
    if (
      !window.confirm(
        'Delete ALL data: every job for every user, including all uploaded files and outputs?',
      )
    )
      return
    setBusy(true)
    setError(null)
    try {
      await api.clearAllJobs()
      await load()
    } catch (e) {
      // surfaces e.g. the 409 "a job is still running — cancel it first"
      setError(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <div>
          <p className="text-sm font-medium text-zinc-200">Require approval for new sign-ups</p>
          <p className="mt-0.5 text-xs text-zinc-500">
            When on, new accounts start pending until an admin approves them.
          </p>
        </div>
        <button
          type="button"
          disabled={!settings || busy}
          onClick={() => settings && void toggleApproval(!settings.require_approval)}
          className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition ${
            settings?.require_approval ? 'bg-emerald-500' : 'bg-zinc-700'
          }`}
          aria-label="Toggle approval requirement"
        >
          <span
            className={`inline-block h-5 w-5 transform rounded-full bg-white transition ${
              settings?.require_approval ? 'translate-x-[22px]' : 'translate-x-0.5'
            }`}
          />
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-900/60 bg-red-950/40 p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border border-zinc-800">
        {/* min-w-max: keep the table's natural width on phones (scrolls), w-full on desktop */}
        <table className="w-full min-w-max text-left text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-xs uppercase tracking-wide text-zinc-500">
              <th className="px-3 py-2 font-medium">Job</th>
              <th className="px-3 py-2 font-medium">Owner</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Created</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {(jobs ?? []).map((j) => (
              <tr key={j.id} className="border-b border-zinc-800/60">
                <td className="max-w-55 truncate px-3 py-2 font-medium text-zinc-100" title={j.source_name}>
                  {j.source_name}
                </td>
                <td className="px-3 py-2 text-zinc-400">{j.owner ?? '—'}</td>
                <td className={`px-3 py-2 ${statusCls[j.status]}`}>
                  {j.status === 'running' ? `running ${j.progress}%` : j.status}
                </td>
                <td className="px-3 py-2 text-zinc-400">{fmtDate(j.created_at)}</td>
                <td className="px-3 py-2 text-right">
                  <button
                    onClick={() => void deleteJob(j.id)}
                    className="rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1 text-xs text-red-400 hover:border-red-900"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {jobs && jobs.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-4 text-center text-zinc-600">
                  No jobs.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-900/60 bg-red-950/20 p-4">
        <div>
          <p className="text-sm font-medium text-red-300">Delete all data</p>
          <p className="mt-0.5 text-xs text-zinc-500">
            Removes every job for every user, plus all uploaded files and outputs.
          </p>
        </div>
        <button
          onClick={() => void deleteAll()}
          disabled={busy}
          className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-500 disabled:opacity-40"
        >
          {busy ? 'Deleting…' : 'Delete all data'}
        </button>
      </div>
    </div>
  )
}
