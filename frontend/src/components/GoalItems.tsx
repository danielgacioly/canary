import { api } from '../api/client'
import type { Goal, TeamGoal } from '../api/types'
import type { CheckKind } from '../features/Checks'
import { useSession } from '../state/session'
import { Icon } from './ui'

export function GoalRow({ g, crewId, onCheck, readOnly, compact }: { g: Goal; crewId: string; onCheck?: (k: CheckKind) => void; readOnly?: boolean; compact?: boolean }) {
  const { bump, toast } = useSession()
  const toggle = async () => {
    if (readOnly) return
    if (!g.done && g.action && onCheck) { onCheck(g.action as CheckKind); return }
    await api.setGoal(crewId, g.id, !g.done)
    if (!g.done) toast(`Done · +${g.xp} XP`)
    bump()
  }
  return (
    <div className={`goal ${g.done ? 'done' : ''}`}>
      <button className="chk" onClick={toggle} aria-label={g.done ? 'Mark as not done' : 'Mark as done'} disabled={readOnly}><Icon name="check" size={14} /></button>
      <div className="grow">
        <div className="gt">{g.title}</div>
        {!compact && <div className="small dim">{g.why}</div>}
      </div>
      {g.by !== 'routine' && <span className="tag">{g.by === 'medical' ? 'From the doctor' : 'From an alert'}</span>}
      <span className="xp">{g.xp} XP</span>
    </div>
  )
}

export function TeamRow({ t, names }: { t: TeamGoal; names: Record<string, string> }) {
  return (
    <div className="team-row col" style={{ gap: 10 }}>
      <div className="row" style={{ alignItems: 'flex-start' }}>
        <div className="grow"><div style={{ fontWeight: 600 }}>{t.title}</div><div className="small muted">{t.area === 'mental' ? 'Mental' : 'Physical'} · {t.xp} XP for everyone</div></div>
        {t.done && <span className="status s0"><span className="dot" />Done</span>}
      </div>
      <div className="row">
        <div className="bar-track grow" style={{ ['--pc' as string]: t.done ? 'var(--ok)' : 'var(--accent)' }}><i style={{ width: `${t.pct}%` }} /></div>
        <span className="num small muted">{t.value.toLocaleString('en-US')}/{t.target.toLocaleString('en-US')} {t.unit}</span>
      </div>
      <div className="small dim">{Object.entries(t.contrib).map(([id, n]) => `${names[id]?.split(' ')[0]} ${n.toLocaleString('en-US')}`).join(' · ')}</div>
    </div>
  )
}
