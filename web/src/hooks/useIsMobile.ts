import { useEffect, useState } from 'react'

const QUERY = '(max-width: 767px)'

// Tracks the phone breakpoint so App can render a single-pane phone tree
// instead of the two-pane desktop layout. (Tailwind can't branch tree
// shape on a breakpoint, so the media query lives in state.)
export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState<boolean>(() =>
    typeof window !== 'undefined' ? window.matchMedia(QUERY).matches : false,
  )

  useEffect(() => {
    const mql = window.matchMedia(QUERY)
    const onChange = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    setIsMobile(mql.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  return isMobile
}
