import { useEffect, useState } from 'react'
import * as api from '../../lib/api'
import type { UsageSummary } from '../../lib/types'
import { errMsg, fmtBytes, fmtDuration, fmtNum } from './format'

export default function AdminUsage() {
  const [data, setData] = useState<UsageSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .usage()
      .then(setData)
      .catch((e) => setError(errMsg(e)))
  }, [])

  if (error) {
    return (
      <div className="rounded-lg border border-red-900/60 bg-red-950/40 p-3 text-sm text-red-300">
        {error}
      </div>
    )
  }
  if (!data) return <p className="text-sm text-zinc-500">Loading…</p>

  const t = (key: string) => data.totals[key] ?? 0

  return (
    <div className="overflow-x-auto rounded-xl border border-zinc-800">
      {/* min-w-max: keep the table's natural width on phones (scrolls), w-full on desktop */}
      <table className="w-full min-w-max text-left text-sm">
        <thead>
          <tr className="border-b border-zinc-800 text-xs uppercase tracking-wide text-zinc-500">
            <th className="px-3 py-2 font-medium">User</th>
            <th className="px-3 py-2 text-right font-medium">Jobs</th>
            <th className="px-3 py-2 text-right font-medium">Uploaded</th>
            <th className="px-3 py-2 text-right font-medium">Prompt tokens</th>
            <th className="px-3 py-2 text-right font-medium">Completion tokens</th>
            <th className="px-3 py-2 text-right font-medium">Transcript time</th>
          </tr>
        </thead>
        <tbody>
          {data.users.map((u) => (
            <tr key={u.username} className="border-b border-zinc-800/60">
              <td className="px-3 py-2 font-medium text-zinc-100">
                {u.username}
                {u.is_admin && <span className="ml-1 text-xs text-emerald-400">· admin</span>}
              </td>
              <td className="px-3 py-2 text-right text-zinc-400">{fmtNum(u.jobs)}</td>
              <td className="px-3 py-2 text-right text-zinc-400">{fmtBytes(u.bytes)}</td>
              <td className="px-3 py-2 text-right text-zinc-400">{fmtNum(u.prompt_tokens)}</td>
              <td className="px-3 py-2 text-right text-zinc-400">{fmtNum(u.completion_tokens)}</td>
              <td className="px-3 py-2 text-right text-zinc-400">{fmtDuration(u.duration_sec)}</td>
            </tr>
          ))}
          {data.users.length === 0 && (
            <tr>
              <td colSpan={6} className="px-3 py-4 text-center text-zinc-600">
                No usage yet.
              </td>
            </tr>
          )}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-zinc-800 font-medium text-zinc-100">
            <td className="px-3 py-2">Total</td>
            <td className="px-3 py-2 text-right">{fmtNum(t('jobs'))}</td>
            <td className="px-3 py-2 text-right">{fmtBytes(t('bytes'))}</td>
            <td className="px-3 py-2 text-right">{fmtNum(t('prompt_tokens'))}</td>
            <td className="px-3 py-2 text-right">{fmtNum(t('completion_tokens'))}</td>
            <td className="px-3 py-2 text-right">{fmtDuration(t('duration_sec'))}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
