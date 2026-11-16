// Shown while the server cannot be reached. It says so plainly: figures on screen may be old, and nothing is sent until the
// connection is back. It checks again every 10 s while offline, and hides as soon as the server answers.
import { useEffect, useState } from 'react'

const CHECK_EVERY_MS = 10_000

export default function OfflineBanner() {
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    const onConnection = (e: Event) => setOffline(!(e as CustomEvent<boolean>).detail)
    window.addEventListener('canary:connection', onConnection)
    return () => window.removeEventListener('canary:connection', onConnection)
  }, [])

  useEffect(() => {
    if (!offline) return
    let live = true
    const probe = async () => {
      try {
        const r = await fetch('/api/health/live', { cache: 'no-store' })
        if (live && r.ok) setOffline(false)
      } catch { /* still offline: the banner stays */ }
    }
    const t = setInterval(probe, CHECK_EVERY_MS)
    return () => { live = false; clearInterval(t) }
  }, [offline])

  if (!offline) return null
  return (
    <div role="status" aria-live="polite" data-testid="offline-banner"
      style={{ position: 'sticky', top: 0, zIndex: 1000, padding: '10px 16px', background: '#2a2105', color: 'var(--ink)', borderBottom: '1px solid var(--gold)', fontSize: 14 }}>
      <b>Offline.</b> Canary cannot reach the ship's server. Figures on this screen may be out of date, and nothing you do is sent until the connection is back.
    </div>
  )
}
