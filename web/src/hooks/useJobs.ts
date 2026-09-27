import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as api from '../lib/api'
import { ApiError } from '../lib/api'
import type { Job, UploadOptions } from '../lib/types'

export interface Health {
  ok: boolean
  ffmpeg: boolean
  ollama_reachable: boolean
  ollama_url: string
  resident: Record<string, unknown>
}

const isLive = (j: Job) => j.status === 'queued' || j.status === 'running'

export function useJobs(onAuthLost?: () => void) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)

  // Always call the latest callback without re-creating refresh each render.
  const onAuthLostRef = useRef(onAuthLost)
  onAuthLostRef.current = onAuthLost

  const refresh = useCallback(async () => {
    try {
      const list = await api.listJobs()
      setJobs(list)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        // Session expired (e.g. signed out in another tab) — hand back to the
        // App to drop the session and show the login screen.
        onAuthLostRef.current?.()
      }
      /* backend not up yet; ignore */
    }
  }, [])

  // Health once at mount.
  useEffect(() => {
    api.fetchHealth().then(setHealth).catch(() => setHealth(null))
  }, [])

  // Poll the list as the source of truth (picks up new/finished jobs and is
  // the reconnect fallback).
  useEffect(() => {
    refresh()
    const iv = setInterval(refresh, 1200)
    return () => clearInterval(iv)
  }, [refresh])

  const selected = useMemo(
    () => jobs.find((j) => j.id === selectedId) || null,
    [jobs, selectedId],
  )

  // Smooth progress: SSE on the selected live job. The server snapshot is a
  // full job row, so it replaces the row in place. (Polling remains the
  // fallback so a dropped SSE still converges within ~1.2 s.)
  const selectedStatus = selected?.status
  useEffect(() => {
    if (!selectedId || !selectedStatus || !isLive({ status: selectedStatus } as Job)) return
    const close = api.subscribeJob(selectedId, (snap) => {
      setJobs((prev) => prev.map((j) => (j.id === snap.id ? { ...j, ...snap } : j)))
    })
    return close
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, selectedStatus])

  const select = useCallback((id: string | null) => setSelectedId(id), [])

  const submitJob = useCallback(
    async (file: Blob, fileName: string, opts: UploadOptions) => {
      const job = await api.createJob(file, fileName, opts)
      setSelectedId(job.id)
      await refresh()
      return job
    },
    [refresh],
  )

  const cancel = useCallback(async (id: string) => {
    try {
      const j = await api.cancelJob(id)
      setJobs((prev) => prev.map((x) => (x.id === id ? { ...x, ...j } : x)))
    } catch {
      /* ignore */
    }
  }, [])

  const clearHistory = useCallback(async () => {
    const ok = window.confirm('Delete all your jobs and their files?')
    if (!ok) return
    try {
      await api.clearMyJobs()
      setSelectedId(null)
      await refresh()
    } catch (e) {
      window.alert(`Could not delete your jobs: ${e instanceof Error ? e.message : String(e)}`)
    }
  }, [refresh])

  const deleteJob = useCallback(
    async (id: string) => {
      const ok = window.confirm('Delete this job and its files?')
      if (!ok) return
      try {
        await api.deleteJob(id)
        setSelectedId(null)
        await refresh()
      } catch (e) {
        window.alert(`Could not delete job: ${e instanceof Error ? e.message : String(e)}`)
      }
    },
    [refresh],
  )

  return { jobs, selected, selectedId, select, submitJob, cancel, clearHistory, deleteJob, health }
}
