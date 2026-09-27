import { useCallback, useEffect, useState } from 'react'
import * as api from '../lib/api'
import { ApiError } from '../lib/api'
import type { User } from '../lib/types'

export function useSession() {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  // Re-check the session (used after login/signup and by App on 401s).
  const refresh = useCallback(async () => {
    try {
      setUser(await api.me())
    } catch (e) {
      // 401 = no session; anything else (backend down) leaves state as-is.
      if (e instanceof ApiError && e.status === 401) setUser(null)
    }
  }, [])

  useEffect(() => {
    let alive = true
    api
      .me()
      .then((u) => {
        if (alive) setUser(u)
      })
      .catch((e) => {
        if (alive && e instanceof ApiError && e.status === 401) setUser(null)
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  const signOut = useCallback(async () => {
    try {
      await api.logout()
    } catch {
      /* already signed out or backend down */
    }
    setUser(null)
  }, [])

  return { user, loading, refresh, signOut }
}
