// Goals as a dashboard: your level, today's physical and mental goals side by side,
// crew missions, then patches.
import { useState } from 'react'
import { api } from '../api/client'
import { GoalRow, TeamRow } from '../components/GoalItems'
import { EnterGate } from '../components/People'
import { CountUp, Loading, Patch } from '../components/ui'
import Check, { type CheckKind } from '../features/Checks'
import { useApi, useSession } from '../state/session'

export default function Goals() {
  const { me } = useSession()
  if (!me) return <EnterGate what="your goals" />
  return <MyGoals me={me} />
}

function MyGoals({ me }: { me: string }) {
  const { catalog } = useSession()
  const { data } = useApi(() => api.goals(me), [me])
  const [check, setCheck] = useState<CheckKind | null>(null)
  if (!data || !catalog) return <Loading what="goals" />
  const p = data.profile
  const names = Object.fromEntries(catalog.crew.map(c => [c.id, c.name]))
  const done = data.personal.filter(g => g.done).length
  return (
    <div className="page">
      <div className="head rise"><div><h1>{done} of {data.personal.length} done today</h1>
        <p className="sub">Small wins, every day, as a crew. A hard day reported honestly earns the same as a good one.</p></div></div>

      <div className="stats">
        <div className="stat rise"><div className="k">Level</div><b className="num" style={{ color: 'var(--gold)' }}>{p.level}</b>
          <div className="bar-track" style={{ marginTop: 8, ['--pc' as string]: 'var(--gold)' }}><i style={{ width: `${(100 * p.into) / p.need}%` }} /></div><div className="s">{p.need - p.into} XP to level {p.level + 1}</div></div>
        <div className="stat rise" style={{ ['--d' as string]: 1 }}><div className="k">XP this week</div><b className="num"><CountUp value={p.xp_week} /></b><div className="s">Physical {p.xp_week_by_area.physical} · Mental {p.xp_week_by_area.mental}</div></div>
        <div className="stat rise" style={{ ['--d' as string]: 2 }}><div className="k">Streak</div><b className="num"><CountUp value={p.streak} /><small>days</small></b><div className="s">Days with 70% of goals done</div></div>
        <div className="stat rise" style={{ ['--d' as string]: 3 }}><div className="k">Last 7 days</div><b className="num"><CountUp value={p.completion_7d} /><small>%</small></b><div className="s">of goals done</div></div>
      </div>

      <section className="grid g2">
        {(['physical', 'mental'] as const).map((a, i) => {
          const list = data.personal.filter(g => g.area === a)
          return (
            <div key={a} className="detail-card rise" style={{ ['--d' as string]: 3 + i }}>
              <div className="section-head"><h2>{a === 'physical' ? 'Physical' : 'Mental'}</h2><span className="sub">{list.filter(g => g.done).length} of {list.length}</span></div>
              {list.map(g => <GoalRow key={g.id} g={g} crewId={me} onCheck={setCheck} />)}
            </div>
          )
        })}
      </section>

      <section>
        <div className="section-head rise"><h2>Crew missions this week</h2><span className="sub">Everyone gets the XP when the crew gets there</span></div>
        <div className="grid g2">{data.team.map((t, i) => <div key={t.id} className="rise" style={{ ['--d' as string]: i }}><TeamRow t={t} names={names} /></div>)}</div>
      </section>

      <section>
        <div className="section-head rise"><h2>Patches</h2><span className="sub">{p.badges_earned} of {p.badges.length} earned</span></div>
        <div className="patches">{p.badges.map((b, i) => (
          <div key={b.id} className={`patch rise ${b.earned ? '' : 'off'}`} style={{ ['--d' as string]: i }}>
            <Patch id={b.id} earned={b.earned} /><b>{b.name}</b><span className="small muted">{b.desc}</span>
            <span className="small dim">{b.earned ? 'Earned' : `${b.progress} of ${b.need}`}</span>
          </div>))}</div>
      </section>
      {check && <Check kind={check} onClose={() => setCheck(null)} />}
    </div>
  )
}
