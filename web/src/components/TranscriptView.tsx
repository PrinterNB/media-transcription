import type { Job } from '../lib/types'

// Deterministic color per speaker id (hashed -> hue), so chips are stable.
const HUES = [152, 200, 268, 330, 40, 120, 180, 300]
function speakerHue(id: string): number {
  let h = 0
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0
  return HUES[h % HUES.length]
}

function fmtTime(t: number): string {
  const h = Math.floor(t / 3600)
  const m = Math.floor((t % 3600) / 60)
  const s = Math.floor(t % 60)
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
              : `${m}:${String(s).padStart(2, '0')}`
}

export default function TranscriptView({ job }: { job: Job }) {
  const map = job.speaker_map || {}
  const segments = job.segments || []

  const nameFor = (id: string | null): string => {
    if (!id || id === 'SPEAKER_UNKNOWN') return 'Speaker'
    const info = map[id]
    if (info?.name) return info.name
    // "SPEAKER_02" -> "Speaker 2"
    const m = /(\d+)$/.exec(id)
    return m ? `Speaker ${m[1]}` : 'Speaker'
  }

  const evidenceFor = (id: string | null): string | null => {
    if (!id) return null
    return map[id]?.evidence || null
  }

  let lastSpeaker: string | null = null

  return (
    <div className="space-y-1">
      {segments.map((seg, i) => {
        const showSpeaker = seg.speaker !== lastSpeaker
        lastSpeaker = seg.speaker
        const name = nameFor(seg.speaker)
        const evidence = evidenceFor(seg.speaker)
        const hue = seg.speaker ? speakerHue(seg.speaker) : 0
        return (
          <div key={i} className="flex gap-3 px-2 py-1.5 hover:bg-zinc-900/40 rounded">
            <span className="w-14 shrink-0 select-none text-right font-mono text-xs leading-5 text-zinc-600">
              {fmtTime(seg.start)}
            </span>
            {showSpeaker && seg.speaker ? (
              <span
                title={evidence || undefined}
                className="max-w-40 shrink-0 cursor-default select-none self-start truncate rounded-full px-2 py-0.5 text-xs font-semibold"
                style={{
                  backgroundColor: `hsl(${hue} 40% 18%)`,
                  color: `hsl(${hue} 80% 72%)`,
                }}
              >
                {name}
              </span>
            ) : (
              <span className="w-16 shrink-0" />
            )}
            <span className="text-sm leading-5 text-zinc-200">{seg.text}</span>
          </div>
        )
      })}
      {segments.length === 0 && (
        <p className="py-8 text-center text-sm text-zinc-600">No transcript yet.</p>
      )}
    </div>
  )
}
