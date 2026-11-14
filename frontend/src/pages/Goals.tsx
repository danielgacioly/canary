// Goals: one tab at a time. Today's goals first, then crew missions, ranking and patches.
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { GoalRow, TeamRow } from '../components/GoalItems'
import { Loading, Patch, Tabs } from '../components/ui'
import Check, { type CheckKind } from '../features/Checks'
import { useApi, useSession } from '../state/session'
import RankingView from './Ranking'

type Tab = 'today' | 'crew' | 'ranking' | 'patches'

export default function Goals() {
  const { me, catalog } = useSession()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab) || 'today'
  const setTab = (t: Tab) => setParams(t === 'today' ? {} : { tab: t }, { replace: true })
  const { data } = useApi(() => (me ? api.goals(me) : Promise.reject(new Error('no user'))), [me])
  const [area, setArea] = useState<'physical' | 'mental'>('physical')
  const [check, setCheck] = useState<CheckKind | null>(null)
  if (!data || !me || !catalog) return <Loading what="goals" />
  const p = data.profile
  const list = data.personal.filter(g => g.area === area)
  const doneAll = data.personal.filter(g => g.done).length
  const names = Object.fromEntries(catalog.crew.map(c => [c.id, c.name]))
  return (
    <div className="page">
      <div className="head">
        <div><h1>Goals</h1><p className="sub">{doneAll} of {data.personal.length} done today · level {p.level} · {p.streak}-day streak</p></div>
        <div className="right" style={{ minWidth: 240 }}>
          <div className="row small"><span className="muted">Level {p.level}</span><span className="right num muted">{p.into}/{p.need} XP</span></div>
          <div className="bar-track" style={{ marginTop: 6, ['--pc' as string]: 'var(--gold)' }}><i style={{ width: `${(100 * p.into) / p.need}%` }} /></div>
        </div>
      </div>
      <Tabs value={tab} onChange={setTab} options={[['today', 'Today'], ['crew', 'Crew missions'], ['ranking', 'Ranking'], ['patches', 'Patches']]} />

      {tab === 'today' && (
        <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1fr) 300px', alignItems: 'start', gap: 24 }}>
          <section className="card">
            <div className="row" style={{ marginBottom: 6 }}>
              {(['physical', 'mental'] as const).map(a => {
                const g = data.personal.filter(x => x.area === a)
                return <button key={a} className={`btn sm ${area === a ? '' : 'ghost'}`} onClick={() => setArea(a)}>{a === 'physical' ? 'Physical' : 'Mental'} · {g.filter(x => x.done).length}/{g.length}</button>
              })}
            </div>
            <div>{list.map(g => <GoalRow key={g.id} g={g} crewId={me} onCheck={setCheck} />)}</div>
          </section>
          <aside className="col" style={{ gap: 16 }}>
            <div className="card pad-sm"><div className="lbl">XP this week</div><div className="big-num num" style={{ marginTop: 6 }}>{p.xp_week}</div>
              <div className="small muted" style={{ marginTop: 6 }}>Physical {p.xp_week_by_area.physical} · Mental {p.xp_week_by_area.mental}</div></div>
            <div className="card pad-sm"><div className="lbl">Goals done, last 7 days</div><div className="big-num num" style={{ marginTop: 6 }}>{p.completion_7d}<small>%</small></div></div>
            <p className="small dim">Ticking a goal earns XP. A hard day reported honestly earns the same as a good one.</p>
          </aside>
        </div>
      )}

      {tab === 'crew' && <div className="grid g2">{data.team.map(t => <TeamRow key={t.id} t={t} names={names} />)}</div>}
      {tab === 'ranking' && <RankingView />}
      {tab === 'patches' && (
        <div className="patches">{p.badges.map(b => (
          <div key={b.id} className={`patch ${b.earned ? '' : 'off'}`}>
            <Patch id={b.id} earned={b.earned} /><b>{b.name}</b><span className="small muted">{b.desc}</span>
            <span className="small dim">{b.earned ? 'Earned' : `${b.progress} of ${b.need}`}</span>
          </div>))}</div>
      )}
      {check && <Check kind={check} onClose={() => setCheck(null)} />}
    </div>
  )
}
