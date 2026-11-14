// NASA's five hazards of human spaceflight (RIDGE), as levels for a place. Tap one to see
// which body systems it acts on. Same for everyone on board, so it is public.
import { useState } from 'react'
import type { Ridge } from '../api/types'

export function Meter({ level }: { level: number }) {
  return <span className={`meter s${level}`} aria-hidden="true">{[0, 1, 2].map(k => <i key={k} className={k <= level ? 'on' : ''} />)}</span>
}

export default function Hazards({ items, compact = false }: { items: Ridge[]; compact?: boolean }) {
  const [open, setOpen] = useState<string | null>(null)
  const sel = items.find(h => h.id === open)
  return (
    <div className={`ridge ${compact ? 'compact' : ''}`}>
      <div className="ridge-grid">
        {items.map(h => (
          <button key={h.id} type="button" className={`ridge-item s${h.level} ${open === h.id ? 'on' : ''}`} onClick={() => setOpen(o => (o === h.id ? null : h.id))} aria-expanded={open === h.id}>
            <span className="row" style={{ gap: 8 }}><Meter level={h.level} /><span className="ridge-lv">{h.label}</span></span>
            <b>{h.name}</b>
            {!compact && <span className="small muted">{h.here}</span>}
          </button>
        ))}
      </div>
      {sel && (
        <div className="ridge-detail" key={sel.id}>
          <p><b>{sel.name}.</b> <span className="muted">{sel.what}</span></p>
          <p className="small muted">Here: {sel.here}. Acts on {sel.system_names.join(', ').toLowerCase()}.</p>
        </div>
      )}
    </div>
  )
}
