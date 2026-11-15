import { useState } from 'react'
import { api } from '../api/client'
import type { Goal, TeamGoal } from '../api/types'
import type { CheckKind } from '../features/Checks'
import { useAction } from '../lib/useAction'
import { useSession } from '../state/session'
import { Icon } from './ui'

/** The one quiet line under a goal: why, or, when it applies, the lightened load for fatigue and the advice check. */
function goalLine(g: Goal): string {
  const parts: string[] = []
  if (g.adjusted) parts.push(`Lightened for fatigue; your team allows up to ${g.adjusted.max_pct}%`)
  // "Added by the alert: ..." says again what the "From an alert" tag already shows.
  else if (!(g.by === 'alert' && g.why.startsWith('Added by the alert'))) parts.push(g.why)
  if (g.advice) parts.push(g.advice.status === 'pending' ? `Check on day ${g.advice.check_day}` : `Checked on day ${g.advice.check_day}: ${g.advice.status === 'same' ? 'no change' : g.advice.status}`)
  return parts.join(' · ')
}

export function GoalRow({ g, crewId, onCheck, readOnly, compact }: { g: Goal; crewId: string; onCheck?: (k: CheckKind) => void; readOnly?: boolean; compact?: boolean }) {
  const { bump, toast } = useSession()
  const act = useAction('toast')
  const toggle = () => {
    if (readOnly) return
    if (!g.done && g.action && onCheck) { onCheck(g.action as CheckKind); return }
    act.run(async () => {
      await api.setGoal(crewId, g.id, !g.done)
      if (!g.done) toast('Goal done')
      bump()
    })
  }
  return (
    <div className={`goal ${g.done ? 'done' : ''}`}>
      <button className="chk" onClick={toggle} aria-label={g.done ? 'Mark as not done' : 'Mark as done'} disabled={readOnly || act.busy}><Icon name="check" size={14} /></button>
      <div className="grow">
        <div className="gt">{g.title}</div>
        {!compact && goalLine(g) && <div className="small dim quiet">{goalLine(g)}</div>}
      </div>
      {g.by !== 'routine' && <span className="tag">{g.by === 'medical' ? 'From the doctor' : g.by === 'suggestion' ? 'Your pick' : 'From an alert'}</span>}
    </div>
  )
}

/** A crew mission: title and progress. Tap it for what it is and, in the person's own space, which of their goals count.
 *  `mine` is the signed-in person's own goals; the public Crew page leaves it out and shows nothing personal. */
export function TeamRow({ t, mine }: { t: TeamGoal; mine?: Goal[] }) {
  const [open, setOpen] = useState(false)
  const counting = (mine ?? []).filter(g => t.personal_ids.includes(g.id))
  const num = (x: number) => x.toLocaleString('en-US')
  return (
    <div className={`team-row ${open ? 'open' : ''}`}>
      <button type="button" className="team-head" aria-expanded={open} aria-controls={`mission-${t.id}`} onClick={() => setOpen(o => !o)}>
        <span className="row">
          <span className="goal-title grow">{t.title}</span>
          {t.done && <span className="status s0"><span className="dot" />Done</span>}
        </span>
        <span className="row">
          <span className="bar-track grow" style={{ ['--pc' as string]: t.done ? 'var(--ok)' : 'var(--accent)' }}><i style={{ width: `${t.pct}%` }} /></span>
          <span className="num small muted">{num(t.value)} / {num(t.target)} {t.unit}</span>
        </span>
      </button>
      {open && (
        <div className="team-more" id={`mission-${t.id}`}>
          <p>{t.what}</p>
          <p className="small muted">Counts the last 7 days. {num(t.value)} of {num(t.target)} {t.unit} so far.</p>
          {counting.length > 0 && (
            <div className="team-mine">
              <b className="small">Your goals that move it forward</b>
              <ul className="plain">{counting.map(g => <li key={g.id}>{g.title}<span className="small muted">{g.done ? 'Done today' : 'Not yet today'}</span></li>)}</ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
