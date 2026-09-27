// Summarization dropdown + "chat with transcript". Shown for every job
// (queued/running/done): while running a picked template is stored as a
// pending summary the worker runs before marking the job done; after done,
// picking runs it immediately. Chat is available only on a finished job.
import { useEffect, useRef, useState } from 'react'
import {
  chatWithTranscript,
  fetchSummaryTemplates,
  summarizeJob,
  type ChatMsg,
  type SummaryTemplate,
} from '../lib/api'
import type { Job } from '../lib/types'
import Markdown from './Markdown'

export default function SummaryPanel({ job }: { job: Job }) {
  const [templates, setTemplates] = useState<SummaryTemplate[]>([])
  const [selected, setSelected] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // chat
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)
  const chatMap = useRef<Record<string, ChatMsg[]>>({})
  const listEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetchSummaryTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]))
  }, [])

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ block: 'nearest' })
  }, [messages, thinking])

  const done = job.status === 'done'
  const hasTranscript = (job.segments?.length ?? 0) > 0

  // per-job chat history survives switching back within the same page load;
  // the dropdown resets to whatever is (or isn't) pending for the new job
  useEffect(() => {
    setMessages(chatMap.current[job.id] || [])
    setSelected(job.pending_summary || '')
    setError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id])
  const setMsgs = (m: ChatMsg[]) => {
    chatMap.current[job.id] = m
    setMessages(m)
  }

  const pick = async (id: string) => {
    setSelected(id)
    setError(null)
    if (!id) {
      // blank: clear any pending selection
      try {
        await summarizeJob(job.id, null)
      } catch {
        /* best effort */
      }
      return
    }
    setBusy(true)
    try {
      await summarizeJob(job.id, id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const send = async () => {
    const text = input.trim()
    if (!text || thinking) return
    setInput('')
    setMsgs([...messages, { role: 'user', content: text }])
    setThinking(true)
    try {
      const reply = await chatWithTranscript(job.id, text, messages)
      setMsgs([...messages, { role: 'user', content: text }, { role: 'assistant', content: reply }])
    } catch (e) {
      // keep the user's message visible, surface the error
      setMsgs([...messages, { role: 'user', content: text }])
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setThinking(false)
    }
  }

  const labelFor = (id: string) => templates.find((t) => t.id === id)?.label ?? id

  return (
    <div className="border-b border-zinc-800 px-4 py-3">
      <div className="flex items-center gap-2">
        <label className="text-xs font-semibold uppercase tracking-wide text-zinc-500" htmlFor="summary-template">
          Summary
        </label>
        <select
          id="summary-template"
          value={selected}
          onChange={(e) => pick(e.target.value)}
          disabled={busy}
          className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-100 outline-none focus:border-emerald-600"
        >
          <option value="">Choose a template…</option>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.label}
            </option>
          ))}
        </select>
        {busy && <span className="text-xs text-zinc-400">Summarizing…</span>}
      </div>
      {!done && !busy && (
        <p className="mt-1 text-xs text-zinc-500">Will run automatically when transcription finishes.</p>
      )}
      {error && <p className="mt-1 text-xs text-red-400">{error}</p>}

      {job.summaries && Object.keys(job.summaries).length > 0 && (
        <div className="mt-3 space-y-2">
          {Object.entries(job.summaries).map(([id, text]) => (
            <details key={id} className="rounded-lg border border-zinc-800 bg-zinc-900/40">
              <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-zinc-200">
                {labelFor(id)}
              </summary>
              <div className="border-t border-zinc-800 px-3 py-2">
                <Markdown content={text} />
              </div>
            </details>
          ))}
        </div>
      )}

      {done && hasTranscript && (
        <div className="mt-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">Chat with transcript</p>
          <div className="max-h-64 space-y-2 overflow-y-auto">
            {messages.map((m, i) =>
              m.role === 'user' ? (
                <div key={i} className="text-right">
                  <span className="inline-block rounded-lg bg-emerald-950/50 px-3 py-1.5 text-sm font-semibold text-emerald-100">
                    {m.content}
                  </span>
                </div>
              ) : (
                <div key={i} className="text-left">
                  <div className="w-full rounded-lg bg-zinc-800/70 px-3 py-1.5">
                    <Markdown content={m.content} />
                  </div>
                </div>
              )
            )}
            {thinking && <div className="text-left text-xs italic text-zinc-500">Thinking…</div>}
            <div ref={listEndRef} />
          </div>
          <form
            className="mt-2 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              send()
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question about this transcript…"
              className="flex-1 rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-emerald-600"
            />
            <button
              type="submit"
              disabled={thinking || !input.trim()}
              className="rounded-lg border border-emerald-800 bg-emerald-950/40 px-4 py-2 text-sm font-medium text-emerald-200 hover:bg-emerald-900/40 disabled:opacity-50"
            >
              Send
            </button>
          </form>
        </div>
      )}
    </div>
  )
}
