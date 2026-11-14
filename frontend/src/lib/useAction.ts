// A standalone async button (approve, remove, reset, accept, pick a place): runs the call, never leaves the
// promise without a catch, ignores a second press while it runs, and keeps the error where the person can read it.
// `inline` keeps the message in `error` for <ActionError/> next to the button; `toast` uses the app's toast.
import { useCallback, useRef, useState } from 'react'
import { errorText } from '../api/client'
import { useSession } from '../state/session'

export function useAction(mode: 'inline' | 'toast' = 'inline') {
  const { toast } = useSession()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const running = useRef(false)
  /** Resolves with the call's result, or undefined when it failed (the message is already showing). */
  const run = useCallback(async <R,>(fn: () => Promise<R>): Promise<R | undefined> => {
    if (running.current) return undefined
    running.current = true; setBusy(true); setError(null)
    try {
      return await fn()
    } catch (e) {
      const m = errorText(e)
      if (mode === 'toast') toast(m); else setError(m)
      return undefined
    } finally {
      running.current = false; setBusy(false)
    }
  }, [mode, toast])
  return { run, busy, error, clear: () => setError(null) }
}
