// Focus handling for every modal dialog: focus moves in on open, Tab stays inside, Escape closes,
// and focus goes back to the control that opened it when the dialog closes.
import { useEffect, useRef } from 'react'

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

function focusables(box: HTMLElement) {
  return Array.from(box.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(el => el.getClientRects().length > 0)
}

/** Attach the returned ref to the dialog element. `onClose` runs on Escape unless `dismissable` is false. */
export function useDialog<T extends HTMLElement>(onClose: () => void, dismissable = true) {
  const ref = useRef<T>(null)
  const close = useRef(onClose)
  close.current = onClose

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    const box = ref.current
    if (box) {
      const first = box.querySelector<HTMLElement>('[data-autofocus], [autofocus]') ?? focusables(box)[0]
      first?.focus()
    }
    const onKey = (e: KeyboardEvent) => {
      if (!box) return
      if (e.key === 'Escape' && dismissable) {
        e.preventDefault()
        e.stopPropagation()  // keeps listeners under the dialog (for example a PIN pad) from firing as well
        close.current()
        return
      }
      if (e.key !== 'Tab') return
      const items = focusables(box)
      if (!items.length) return
      const first = items[0], last = items[items.length - 1]
      const active = document.activeElement
      if (e.shiftKey && (active === first || !box.contains(active))) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && (active === last || !box.contains(active))) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      if (opener && opener.isConnected) opener.focus()
    }
  }, [dismissable])

  return ref
}
