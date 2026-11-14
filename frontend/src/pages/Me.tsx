import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import HealthBody from '../components/HealthBody'
import { GoalRow } from '../components/GoalItems'
import { Icon, Loading, Pill } from '../components/ui'
import Check, { type CheckKind } from '../features/Checks'
import { useApi, useSession } from '../state/session'

export default function Me() {
  const { me, setEmergency, setAskOpen, mission } = useSession()
  const { data: d, error } = useApi(() => (me ? api.crewDetail(me) : Promise.reject(new Error('no user'))), [me])
  const { data: msgs } = useApi(() => api.messages(me ?? undefined), [me])
  const [check, setCheck] = useState<CheckKind | null>(null)
  if (error) return <div className="page"><p className="muted">Cannot reach the Canary API. Is the backend running on :8000?</p></div>
  if (!d) return <Loading />
  const first = d.crew.name.split(' ')[0]
  const top = d.alerts[0]
  const open = d.goals.filter(g => !g.done)
  const headline = mission?.learning ? 'Learning your normal.' : top ? top.title : 'You are within your normal.'
  return (
    <div className="page">
      <div className="hello">
        <div className="col" style={{ gap: 8 }}>
          <span className="lbl">{d.mission.day_label} · {d.mission.place.name} · {d.crew.role}</span>
          <h1>Hello, <em>{first}</em>. {headline}</h1>
        </div>
        <div className="row right" style={{ gap: 10 }}>
          <Pill level={d.level}>{d.status}</Pill>
          <span className="level-chip">LVL {d.profile.level}</span>
          <span className="tag num">{d.profile.streak}-day streak</span>
        </div>
      </div>

      {mission?.learning && (
        <div className="card alert s0"><b>For the 30 days before launch Canary only records how you sleep, react and feel when you are well.</b>
          <p className="muted small" style={{ marginTop: 4 }}>From launch on, every alert compares you with yourself, never with an average.</p></div>
      )}

      {top && (
        <div className={`card alert glow s${top.level}`}>
          <div className="row wrap" style={{ alignItems: 'flex-start', gap: 18 }}>
            <div className="grow" style={{ minWidth: 260 }}>
              <div className="row"><Pill level={top.level} />{top.env && <span className="tag">environment</span>}{d.alerts.length > 1 && <span className="small dim">+{d.alerts.length - 1} more</span>}</div>
              <p style={{ marginTop: 10 }} className="muted">{top.why}</p>
              <ol className="todo">{top.todo.map(t => <li key={t}>{t}</li>)}</ol>
            </div>
            <div className="col" style={{ minWidth: 220 }}>
              {top.test && <button className="btn pri" onClick={() => setCheck(top.test as CheckKind)}>Take the reaction test</button>}
              {top.protocol && <button className="btn" style={{ borderColor: 'rgba(252,61,33,.6)' }} onClick={() => setEmergency(true)}>Open radiation protocol</button>}
              <button className="btn" onClick={() => setAskOpen(true)}><Icon name="ask" size={15} />Ask Canary why</button>
            </div>
          </div>
        </div>
      )}

      <HealthBody d={d} onCheck={setCheck} />

      <div className="grid" style={{ gridTemplateColumns: 'minmax(0,1.6fr) minmax(0,1fr)' }}>
        <section className="card">
          <div className="head"><h2>Still to do today</h2><span className="tag">{d.goals.length - open.length}/{d.goals.length} done</span><Link to="/goals" className="btn sm right">All goals<Icon name="chev" size={14} /></Link></div>
          <div className="col" style={{ gap: 8 }}>{open.slice(0, 5).map(g => <GoalRow key={g.id} g={g} crewId={d.crew.id} onCheck={setCheck} />)}
            {!open.length && <p className="muted">Everything done. Rest is a goal too.</p>}</div>
        </section>
        <section className="card">
          <div className="head"><h2>Link to Earth</h2><span className="tag">{d.mission.place.reply}</span></div>
          <div className="col" style={{ gap: 10 }}>
            {(msgs ?? []).slice(0, 5).map(m => (
              <div key={m.id} className="row small" style={{ alignItems: 'flex-start' }}>
                <span className={`dot s${m.delivered ? 0 : 1}`} style={{ marginTop: 6 }} />
                <div className="grow"><b>{m.kind === 'text' ? `${m.sender} → ${m.recipient}` : m.kind}</b><div className="muted" style={{ whiteSpace: 'pre-line' }}>{m.text.slice(0, 120)}{m.text.length > 120 ? '…' : ''}</div></div>
                <span className="num dim">{m.delivered ? 'delivered' : `${m.eta_s}s`}</span>
              </div>
            ))}
            {!msgs?.length && <p className="muted small">No traffic yet. Briefings, reports and messages show here with their delay.</p>}
          </div>
        </section>
      </div>
      {check && <Check kind={check} onClose={() => setCheck(null)} />}
    </div>
  )
}
