// The cabin-wide alarm: while any Guided Response is open, every screen shows this red bar (polled every 5 s, no sign-in needed).
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api, errorText } from '../api/client'
import type { OpenEmergency } from '../api/types'
import { useSession } from '../state/session'

export function useOpenEmergencies(): OpenEmergency[] {
  const { rev } = useSession()
  const [open, setOpen] = useState<OpenEmergency[]>([])
  useEffect(() => {
    let live = true
    const load = () => api.emergenciesOpen().then(r => { if (live) setOpen(r) }).catch(() => undefined)
    load()
    const t = setInterval(load, 5000)
    return () => { live = false; clearInterval(t) }
  }, [rev])
  useEffect(() => {
    document.body.classList.toggle('has-alarm', open.length > 0)
    return () => document.body.classList.remove('has-alarm')
  }, [open.length])
  return open
}

export default function EmergencyBanner() {
  const open = useOpenEmergencies()
  const { bump, toast } = useSession()
  const [busy, setBusy] = useState(false)
  if (!open.length) return null
  const e = open[0]
  // Anyone on board can stop an alarm left open (closed by mistake, or opened on another screen). The record keeps it as cancelled.
  const cancel = async () => {
    setBusy(true)
    try {
      await api.emergencyEvent(e.id, { cancel: true })
      toast('Emergency cancelled.')
      bump()
    } catch (err) {
      toast(err instanceof ApiError && (err.status === 401 || err.status === 403)
        ? 'Sign in on board to cancel the emergency.'
        : `The emergency was not cancelled: ${errorText(err)}`)
    } finally { setBusy(false) }
  }
  return (
    <div className="alarm" role="alert">
      <span className="dot" />
      <span className="grow"><b>Emergency in progress:</b> {e.patient ?? 'patient not named yet'}, {e.protocol ?? 'protocol not chosen yet'}{open.length > 1 ? ` (+${open.length - 1} more)` : ''}</span>
      <Link to="/medical">Medical console</Link>
      <button type="button" className="alarm-cancel" onClick={cancel} disabled={busy}>{busy ? 'Cancelling…' : 'Cancel'}</button>
    </div>
  )
}
