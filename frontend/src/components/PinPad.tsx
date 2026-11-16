// A 4-digit PIN pad: four dots, a big keypad, physical keyboard support.
// onSubmit runs on the 4th digit and throws (ApiError) when the PIN is wrong; the pad shakes and clears.
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import { Icon } from './ui'
import { Modal, ModalTitle } from './Modal'

export interface PinPadProps {
  title: string
  subtitle?: string
  /** Small, dim line under the keypad, e.g. "Demo PIN: 1001". */
  hint?: string
  onSubmit: (pin: string) => Promise<void>
  onCancel?: () => void
}

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', 'del'] as const

export default function PinPad({ title, subtitle, hint, onSubmit, onCancel }: PinPadProps) {
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  const [wrong, setWrong] = useState(false)
  const [msg, setMsg] = useState('')
  const alive = useRef(true)
  const busyRef = useRef(false)
  const pinRef = useRef('')
  const set = useCallback((v: string) => { pinRef.current = v; setPin(v) }, [])
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  const submit = useCallback(async (value: string) => {
    busyRef.current = true
    setBusy(true)
    try {
      await onSubmit(value)
      if (alive.current) { set(''); setMsg('') }
    } catch (e) {
      if (!alive.current) return
      setWrong(true)
      setMsg(e instanceof ApiError && e.status === 429 ? 'Too many attempts. Wait a minute and try again.'
        : e instanceof ApiError && e.status === 401 ? 'Wrong PIN. Try again.'
          : e instanceof Error ? e.message : 'Something went wrong.')
      window.setTimeout(() => { if (alive.current) { setWrong(false); set('') } }, 520)
    } finally {
      busyRef.current = false
      if (alive.current) setBusy(false)
    }
  }, [onSubmit, set])

  const press = useCallback((k: string) => {
    if (busyRef.current) return
    setMsg('')
    let p = pinRef.current
    if (k === 'del') p = p.slice(0, -1)
    else if (p.length < 4) p += k
    else return
    set(p)
    if (p.length === 4) {
      busyRef.current = true  // block further keys until the answer comes back
      window.setTimeout(() => submit(p), 140)
    }
  }, [submit, set])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (/^\d$/.test(e.key)) { e.preventDefault(); press(e.key) }
      else if (e.key === 'Backspace') { e.preventDefault(); press('del') }
      else if (e.key === 'Escape' && onCancel) { e.preventDefault(); onCancel() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [press, onCancel])

  return (
    <div className={`pinpad ${wrong ? 'bad' : ''} ${busy ? 'busy' : ''}`} role="group" aria-label={title}>
      <ModalTitle>{title}</ModalTitle>
      {subtitle && <p className="muted">{subtitle}</p>}
      <div className="pin-dots" role="img" aria-label={`${pin.length} of 4 digits entered`}>
        {[0, 1, 2, 3].map(i => <i key={i} className={i < pin.length ? 'on' : ''} />)}
      </div>
      <p className={`pin-msg small ${msg ? 'show' : ''}`} role="alert">{msg || ' '}</p>
      <div className="keypad">
        {KEYS.map((k, i) => k === '' ? <span key={i} /> : (
          <button key={k} type="button" className={k === 'del' ? 'del' : ''} disabled={busy || (k === 'del' && !pin)} onClick={() => press(k)}
            aria-label={k === 'del' ? 'Delete last digit' : `Digit ${k}`}>
            {k === 'del' ? <Icon name="backspace" size={22} /> : k}
          </button>
        ))}
      </div>
      {hint && <p className="small dim">{hint}</p>}
      {onCancel && <button type="button" className="link pin-cancel" onClick={onCancel}>Cancel</button>}
    </div>
  )
}

/** A PinPad in a dialog over the page. Click outside or press Escape to close. Its title names the dialog. */
export function PinModal({ onCancel, children }: { onCancel: () => void; children: ReactNode }) {
  return <Modal onClose={onCancel} className="pinmodal">{children}</Modal>
}
