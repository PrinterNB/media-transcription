import { downloadUrl } from '../lib/api'
import type { Job } from '../lib/types'

const FMTS: { key: 'txt' | 'srt' | 'vtt' | 'json'; label: string }[] = [
  { key: 'txt', label: 'TXT' },
  { key: 'srt', label: 'SRT' },
  { key: 'vtt', label: 'VTT' },
  { key: 'json', label: 'JSON' },
]

export default function DownloadBar({ job }: { job: Job }) {
  return (
    <div className="flex items-center gap-2 border-b border-zinc-800 px-4 py-2">
      <span className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
        Download
      </span>
      <div className="flex gap-1.5">
        {FMTS.map((f) => (
          <a
            key={f.key}
            href={downloadUrl(job.id, f.key)}
            download
            className="rounded-md border border-zinc-800 bg-zinc-900 px-2.5 py-1 text-xs font-medium text-zinc-300 hover:border-zinc-700 hover:text-zinc-100"
          >
            {f.label}
          </a>
        ))}
      </div>
    </div>
  )
}
