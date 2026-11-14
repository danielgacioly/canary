import { api } from '../api/client'
import type { Goal, TeamGoal } from '../api/types'
import type { CheckKind } from '../features/Checks'
import { useSession } from '../state/session'
import { Icon } from './ui'

export function GoalRow({ g, crewId, onCheck, readOnly }: { g: Goal; crewId: string; onCheck?: (k: CheckKind) => void; readOnly?: boolean }) {
  const { bump, toast } = useSession()
  const toggle = async () => {
    if (readOnly) return
    if (!g.done && g.action && onCheck) { onCheck(g.action as CheckKind); return }
    await api.setGoal(crewId, g.id, !g.done)
    if (!g.done) toast(`+${g.xp} XP · ${g.title}`)
    bump()
  }
  return (
    <div className={`goal ${g.done ? 'done' : ''}`}>
      <button className="chk" onClick={toggle} aria-label={g.done ? 'Mark as not done' : 'Mark as done'} disabled={readOnly}><Icon name="check" /></button>
      <div className="grow">
        <div className="gt" style={{ fontWeight: 600 }}>{g.title}</div>
        <div className="small dim">{g.why}</div>
      </div>
      {g.by !== 'routine' && <span className={`tag ${g.by === 'medical' ? 'phys' : ''}`} style={g.by === 'alert' ? { color: 'var(--watch)' } : undefined}>{g.by === 'medical' ? 'Medical team' : 'From alert'}</span>}
      {g.action && !g.done && !readOnly && <span className="tag">opens check</span>}
      <span className="xp">+{g.xp} XP</span>
    </div>
  )
}

export function TeamRow({ t, names }: { t: TeamGoal; names: Record<string, string> }) {
  const col = t.area === 'mental' ? 'var(--mental)' : 'var(--physical)'
  const max = Math.max(1, ...Object.values(t.contrib))
  return (
    <div className="card tight flat" style={{ display: 'flex', flexDirection: 'column', gap: 10, borderColor: t.done ? 'rgba(61,220,151,.3)' : undefined }}>
      <div className="row">
        <span className={`tag ${t.area === 'mental' ? 'ment' : 'phys'}`}>{t.area}</span>
        <b className="grow">{t.title}</b>
        {t.done ? <span className="pill s0"><span className="dot" />Complete</span> : <span className="xp">+{t.xp} XP each</span>}
      </div>
      <div className="row">
        <div className="prog grow" style={{ ['--pc' as string]: col }}><i style={{ width: `${t.pct}%` }} /></div>
        <span className="num small" style={{ minWidth: 92, textAlign: 'right' }}>{t.value.toLocaleString()} / {t.target.toLocaleString()} {t.unit}</span>
      </div>
      <div className="row wrap" style={{ gap: 12 }}>
        {Object.entries(t.contrib).map(([id, n]) => (
          <span key={id} className="row small" style={{ gap: 6 }}>
            <span className="dim">{names[id]?.split(' ')[0]}</span>
            <span style={{ width: 46, height: 4, borderRadius: 4, background: 'rgba(150,178,230,.12)', overflow: 'hidden', display: 'inline-block' }}>
              <i style={{ display: 'block', height: '100%', width: `${(100 * n) / max}%`, background: col }} />
            </span>
          </span>
        ))}
      </div>
    </div>
  )
}
