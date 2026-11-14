import { useState } from 'react'
import { api } from '../api/client'
import { GoalRow, TeamRow } from '../components/GoalItems'
import { CountUp, Loading, Patch } from '../components/ui'
import Check, { type CheckKind } from '../features/Checks'
import { useApi, useSession } from '../state/session'

export default function Goals() {
  const { me, catalog } = useSession()
  const { data } = useApi(() => (me ? api.goals(me) : Promise.reject(new Error('no user'))), [me])
  const [tab, setTab] = useState<'personal' | 'team'>('personal')
  const [check, setCheck] = useState<CheckKind | null>(null)
  if (!data || !me || !catalog) return <Loading what="goals" />
  const p = data.profile
  const names = Object.fromEntries(catalog.crew.map(c => [c.id, c.name]))
  const phys = data.personal.filter(g => g.area === 'physical'), ment = data.personal.filter(g => g.area === 'mental')
  const pct = Math.round((100 * p.into) / p.need)
  const maxDay = Math.max(1, ...p.daily_xp.map(d => d[1]))
  return (
    <div className="page">
      <div className="hello">
        <div className="col" style={{ gap: 8 }}><span className="lbl">Goals</span><h1>Small wins, every day, as a crew.</h1></div>
        <div className="seg right"><button className={tab === 'personal' ? 'on' : ''} onClick={() => setTab('personal')}>Personal</button><button className={tab === 'team' ? 'on' : ''} onClick={() => setTab('team')}>Crew missions</button></div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'minmax(0,1.1fr) minmax(0,1fr) minmax(0,1fr)' }}>
        <div className="card col">
          <div className="row"><span className="level-chip">LEVEL {p.level}</span><span className="small muted right">{p.into} / {p.need} XP to next</span></div>
          <div className="prog" style={{ ['--pc' as string]: 'var(--gold)' }}><i style={{ width: `${pct}%` }} /></div>
          <div className="row" style={{ gap: 26, marginTop: 6 }}>
            <div className="kpi"><span className="lbl">Total XP</span><b className="num"><CountUp value={p.xp_total} /></b></div>
            <div className="kpi"><span className="lbl">This week</span><b className="num">{p.xp_week}</b></div>
            <div className="kpi"><span className="lbl">Streak</span><b className="num">{p.streak}<small>days</small></b></div>
          </div>
        </div>
        <div className="card col">
          <span className="lbl">XP this week by area</span>
          {(['physical', 'mental'] as const).map(a => (
            <div key={a} className="col" style={{ gap: 6 }}>
              <div className="row"><span className={`tag ${a === 'mental' ? 'ment' : 'phys'}`}>{a}</span><span className="num right">{p.xp_week_by_area[a]} XP</span></div>
              <div className="prog" style={{ ['--pc' as string]: a === 'mental' ? 'var(--mental)' : 'var(--physical)' }}><i style={{ width: `${(100 * p.xp_week_by_area[a]) / Math.max(1, p.xp_week)}%` }} /></div>
            </div>))}
          <span className="small dim">Team XP from completed crew missions: {p.team_xp}</span>
        </div>
        <div className="card col">
          <span className="lbl">Last 14 days</span>
          <div className="row" style={{ alignItems: 'flex-end', gap: 4, height: 92 }}>
            {p.daily_xp.map(([d, x]) => <div key={d} title={`Day ${d}: ${x} XP`} style={{ flex: 1, height: `${(100 * x) / maxDay}%`, minHeight: 2, borderRadius: 3, background: 'linear-gradient(180deg, var(--gold), rgba(255,207,92,.25))' }} />)}
          </div>
          <span className="small dim">Completion last 7 days: {p.completion_7d}%</span>
        </div>
      </div>

      {tab === 'personal' ? (
        <div className="grid g2">
          {([['physical', phys, 'var(--physical)', 'Body: exercise, water, vitals, mobility, nutrition, vision.'], ['mental', ment, 'var(--mental)', 'Mind: sleep, focus, meditation, reading, crew time, films and music, home.']] as const).map(([a, list, col, sub]) => (
            <section key={a} className="card">
              <div className="head"><div><span className="lbl" style={{ color: col }}>{a}</span><h2 style={{ marginTop: 4 }}>{list.filter(g => g.done).length} of {list.length} done</h2><p className="small dim">{sub}</p></div></div>
              <div className="col" style={{ gap: 8 }}>{list.map(g => <GoalRow key={g.id} g={g} crewId={me} onCheck={setCheck} />)}</div>
            </section>
          ))}
        </div>
      ) : (
        <section className="card">
          <div className="head"><h2>Crew missions this week</h2><span className="small muted">Everyone gets the XP when the crew gets there</span></div>
          <div className="grid g2">{data.team.map(t => <TeamRow key={t.id} t={t} names={names} />)}</div>
        </section>
      )}

      <section className="card">
        <div className="head"><h2>Mission patches</h2></div>
        <div className="patches">{p.badges.map(b => (
          <div key={b.id} className={`patch ${b.earned ? '' : 'off'}`} title={b.desc}>
            <Patch id={b.id} earned={b.earned} area={b.area} /><b>{b.name}</b><span className="small dim">{b.desc}</span>
            {!b.earned && <div className="prog" style={{ width: '80%' }}><i style={{ width: `${(100 * b.progress) / b.need}%` }} /></div>}
          </div>))}</div>
      </section>
      {check && <Check kind={check} onClose={() => setCheck(null)} />}
    </div>
  )
}
