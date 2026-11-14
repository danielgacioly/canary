// Medical console: the only signed-in mode. Flight surgeons and the crew medical officer.
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Briefing, MedGoal, MedicalOverview } from '../api/types'
import { Avatar, Icon, Status, Tabs } from '../components/ui'
import { useApi, useSession } from '../state/session'

const TABS = ['Triage', 'Briefings', 'Prescribe', 'Alert rules', 'Messages', 'Emergencies'] as const

export default function Medical() {
  const [signed, setSigned] = useState(api.isMedical())
  const [tab, setTab] = useState<(typeof TABS)[number]>('Triage')
  const { rev } = useSession()
  const [ov, setOv] = useState<MedicalOverview | null>(null)
  useEffect(() => {
    if (!signed) return
    api.medicalOverview().then(setOv).catch(() => { api.medicalSignOut(); setSigned(false) })
  }, [signed, rev])
  if (!signed) return <PinGate onOk={() => setSigned(true)} />
  return (
    <div className="page">
      <div className="head">
        <div><h1>Medical console</h1><p className="sub">Flight surgeons and the crew medical officer</p></div>
        <button className="btn sm right" onClick={() => { api.medicalSignOut(); setSigned(false) }}>Sign out</button>
      </div>
      <Tabs value={tab} onChange={setTab} options={TABS.map(t => [t, t] as [typeof t, string])} />
      {!ov ? <span className="lbl">Loading…</span> : (
        <>
          {tab === 'Triage' && <Triage ov={ov} />}
          {tab === 'Briefings' && <Briefings ov={ov} />}
          {tab === 'Prescribe' && <Prescribe ov={ov} />}
          {tab === 'Alert rules' && <Rules ov={ov} />}
          {tab === 'Messages' && <Messages />}
          {tab === 'Emergencies' && <Emergencies ov={ov} />}
        </>
      )}
    </div>
  )
}

function PinGate({ onOk }: { onOk: () => void }) {
  const [pin, setPin] = useState(''), [err, setErr] = useState('')
  return (
    <div className="page" style={{ alignItems: 'center', paddingTop: 80 }}>
      <form className="card col" style={{ width: 'min(420px,100%)', gap: 14 }} onSubmit={async e => {
        e.preventDefault()
        try { await api.medicalSignIn(pin); onOk() } catch (x) { setErr((x as Error).message) }
      }}>
        <h2>Medical console</h2>
        <p className="small muted">The crew has no accounts. Only the medical team signs in. Demo PIN: 1961.</p>
        <input type="password" inputMode="numeric" autoComplete="off" maxLength={8} value={pin} onChange={e => setPin(e.target.value)} aria-label="PIN"
          style={{ padding: 12, borderRadius: 10, border: '1px solid var(--line-2)', background: 'var(--bg)', font: '500 22px var(--f-mono)', letterSpacing: '.3em' }} />
        {err && <span className="small" style={{ color: 'var(--act)' }}>{err}</span>}
        <button className="btn pri">Enter</button>
      </form>
    </div>
  )
}

function Triage({ ov }: { ov: MedicalOverview }) {
  const inds = Object.keys(ov.crew[0].indicators)
  return (
    <>
      <div className="grid g4">{ov.crew.map(c => (
        <div key={c.id} className="card col" style={{ gap: 8 }}>
          <div className="row"><b>{c.name}</b><span className="right"><Status level={c.level} /></span></div>
          <span className="small muted">{c.role}</span>
          <div className="row small"><span style={{ color: 'var(--physical)' }}>Physical {c.areas.physical.score}</span><span style={{ color: 'var(--mental)' }}>Mental {c.areas.mental.score}</span></div>
          {c.alerts.slice(0, 3).map(a => <span key={a.id} className={`small s${a.level} c`}>● {a.title}</span>)}
        </div>))}</div>
      <section className="card">
        <div className="head"><h2>Every indicator, every person</h2><span className="small muted">value · deviation from own baseline (σ)</span></div>
        <div className="scroll"><table className="t">
          <thead><tr><th>Indicator</th>{ov.crew.map(c => <th key={c.id}>{c.name.split(' ')[0]}</th>)}</tr></thead>
          <tbody>{inds.map(k => (
            <tr key={k}><td><b>{ov.crew[0].indicators[k].name}</b> <span className="dim small">{ov.crew[0].indicators[k].unit}</span></td>
              {ov.crew.map(c => { const i = c.indicators[k]; return <td key={c.id} className={`num s${i.level}`}><span className={i.level ? 'c' : ''}>{i.value.toFixed(i.dp)}</span> <span className="dim small">{i.z > 0 ? '+' : ''}{i.z.toFixed(1)}</span></td> })}</tr>))}</tbody>
        </table></div>
      </section>
    </>
  )
}

function Briefings({ ov }: { ov: MedicalOverview }) {
  const [who, setWho] = useState(ov.crew[0].id)
  const { data: list, setData } = useApi(() => api.briefings(who), [who])
  const { data: st } = useApi(() => api.assistantStatus(), [])
  const { bump, toast } = useSession()
  const [b, setB] = useState<Briefing | null>(null)
  useEffect(() => setB(list?.[0] ?? null), [list])
  return (
    <div className="grid" style={{ gridTemplateColumns: 'minmax(0,1fr) minmax(0,1.4fr)' }}>
      <section className="card col">
        <h2>Weekly briefing</h2>
        <p className="small muted">Code computes the facts; a model, once connected, only writes the prose and cannot add numbers. The crew member approves it before it is queued for Earth.</p>
        <div className="slot small">{st ? (st.configured ? `Model: ${st.provider}` : 'No model connected: template text from the same facts.') : '…'}</div>
        <div className="row wrap">{ov.crew.map(c => <button key={c.id} className={`btn sm ${who === c.id ? 'pri' : ''}`} onClick={() => setWho(c.id)}>{c.name.split(' ')[0]}</button>)}</div>
        <button className="btn pri" onClick={async () => { const nb = await api.briefing(who); setData([nb, ...(list ?? [])]); setB(nb) }}>Generate briefing</button>
        <div className="list">{(list ?? []).map(x => <button key={x.id} className={`item s${x.status === 'draft' ? 1 : 0}`} onClick={() => setB(x)}><span className="dot" />Day {x.day} · {x.status}<span className="v">{x.bytes} B</span></button>)}</div>
      </section>
      <section className="card">
        {b ? (
          <>
            <div className="head"><span className="tag">{b.mode === 'ai' ? 'AI prose' : 'template'}</span><span className="tag">{b.bytes} bytes</span><Status level={b.status === 'draft' ? 1 : 0}>{b.status}</Status>
              {b.status === 'draft' && <button className="btn sm pri right" onClick={async () => { const nb = await api.approveBriefing(b.id); setB(nb); bump(); toast('Approved by the crew member and queued for Earth.') }}>Approve and queue</button>}</div>
            <pre style={{ whiteSpace: 'pre-wrap', font: '500 13px/1.7 var(--f-mono)', margin: 0, color: 'var(--ink)' }}>{b.text}</pre>
          </>
        ) : <p className="muted">Generate a briefing to see it here.</p>}
      </section>
    </div>
  )
}

function Prescribe({ ov }: { ov: MedicalOverview }) {
  const { bump, toast } = useSession()
  const { data: goals, setData } = useApi(() => api.medGoals(), [])
  const [f, setF] = useState({ who: 'all', area: 'physical', title: '', why: 'Prescribed by the medical team.', days: 7, xp: 20 })
  const inp = { padding: 10, borderRadius: 9, border: '1px solid var(--line-2)', background: 'var(--bg)' }
  return (
    <div className="grid g2">
      <form className="card col" onSubmit={async e => { e.preventDefault(); setData(await api.addMedGoal(f)); bump(); toast('Goal prescribed'); setF({ ...f, title: '' }) }}>
        <h2>Prescribe a goal</h2>
        <label className="col" style={{ gap: 4 }}><span className="lbl">For</span><select style={inp} value={f.who} onChange={e => setF({ ...f, who: e.target.value })}><option value="all">Whole crew</option>{ov.crew.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
        <label className="col" style={{ gap: 4 }}><span className="lbl">Area</span><select style={inp} value={f.area} onChange={e => setF({ ...f, area: e.target.value })}><option value="physical">Physical</option><option value="mental">Mental</option></select></label>
        <label className="col" style={{ gap: 4 }}><span className="lbl">Goal</span><input style={inp} required minLength={3} value={f.title} onChange={e => setF({ ...f, title: e.target.value })} placeholder="e.g. Measure pressure lying and standing, morning and night" /></label>
        <label className="col" style={{ gap: 4 }}><span className="lbl">Why (the crew sees this)</span><input style={inp} value={f.why} onChange={e => setF({ ...f, why: e.target.value })} /></label>
        <div className="grid g2">
          <label className="col" style={{ gap: 4 }}><span className="lbl">Days</span><input style={inp} type="number" min={1} max={60} value={f.days} onChange={e => setF({ ...f, days: +e.target.value })} /></label>
          <label className="col" style={{ gap: 4 }}><span className="lbl">XP</span><input style={inp} type="number" min={5} max={100} value={f.xp} onChange={e => setF({ ...f, xp: +e.target.value })} /></label>
        </div>
        <button className="btn pri">Prescribe</button>
      </form>
      <section className="card"><div className="head"><h2>Active prescriptions</h2></div>
        <div className="col" style={{ gap: 8 }}>{(goals ?? []).map((g: MedGoal) => (
          <div key={g.id} className="goal"><div className="grow"><b>{g.title}</b><div className="small dim">{g.who === 'all' ? 'Whole crew' : ov.crew.find(c => c.id === g.who)?.name} · day {g.from_day} to {g.to_day} · {g.area}</div></div>
            <button className="btn sm" onClick={async () => { setData(await api.delMedGoal(g.id)); bump() }}>Remove</button></div>))}
          {!goals?.length && <p className="muted">None. Guided Response adds follow-up care here automatically.</p>}</div>
      </section>
    </div>
  )
}

function Rules({ ov }: { ov: MedicalOverview }) {
  const { bump, toast } = useSession()
  const [w, setW] = useState(ov.thresholds.watch), [a, setA] = useState(ov.thresholds.act)
  return (
    <section className="card col" style={{ maxWidth: 720 }}>
      <h2>When Canary speaks up</h2>
      <p className="muted">Each indicator is compared with that person's own pre-flight normal. The distance is measured in their personal spread (σ). Lower thresholds mean earlier, more frequent alerts.</p>
      {([['Watch from', w, setW, 'var(--watch)'], ['Act from', a, setA, 'var(--act)']] as const).map(([l, v, set, c]) => (
        <label key={l} className="col" style={{ gap: 6 }}><span className="row"><span className="lbl">{l}</span><b className="num right" style={{ color: c }}>{v.toFixed(1)} σ</b></span>
          <input type="range" min={0.5} max={4.5} step={0.1} value={v} onChange={e => set(+e.target.value)} /></label>
      ))}
      <button className="btn pri" style={{ alignSelf: 'flex-start' }} disabled={a <= w} onClick={async () => { await api.setThresholds(w, a); bump(); toast('Alert rules updated for the whole crew') }}>Apply to crew</button>
      <div className="hr" />
      <span className="lbl">Cross-signal rules (always on)</span>
      <ul className="steps">
        <li>Sleep + mood + reaction time together → behavioural alert, reaction test, 3-night plan</li>
        <li>High pulse + low water in the first 72 h → space sickness, hydration goals</li>
        <li>Low pressure + high pulse in partial gravity → re-adaptation, slow standing</li>
        <li>Wavy Amsler grid → eye alert (SANS screen)</li>
        <li>Solar particle event → everyone to shelter, radiation protocol</li>
      </ul>
    </section>
  )
}

function Messages() {
  const { me, catalog, bump } = useSession()
  const { data } = useApi(() => api.messages(), [])
  const [to, setTo] = useState('crew'), [text, setText] = useState('')
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t) }, [])
  return (
    <div className="grid g2">
      <form className="card col" onSubmit={async e => { e.preventDefault(); await api.send('flight surgeon', to, text); setText(''); bump() }}>
        <h2>Message the crew</h2><p className="small muted">It arrives after the real delay for where the crew is (20× faster in the demo).</p>
        <select value={to} onChange={e => setTo(e.target.value)} style={{ padding: 10, borderRadius: 9, border: '1px solid var(--line-2)', background: 'var(--bg)' }}>
          <option value="crew">Whole crew</option>{catalog?.crew.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
        <textarea required rows={4} value={text} onChange={e => setText(e.target.value)} style={{ padding: 10, borderRadius: 9, border: '1px solid var(--line-2)', background: 'var(--bg)' }} />
        <button className="btn pri" style={{ alignSelf: 'flex-start' }} disabled={!text.trim()}><Icon name="send" size={15} />Send</button>
        <span className="small dim">Signed as flight surgeon{me ? ` · terminal of ${catalog?.crew.find(c => c.id === me)?.name}` : ''}</span>
      </form>
      <section className="card"><div className="head"><h2>Link log</h2></div>
        <div className="col" style={{ gap: 10 }}>{(data ?? []).map(m => {
          const eta = Math.max(0, Math.round(m.deliver_at - Date.now() / 1000))
          return (
            <div key={m.id} className="row small" style={{ alignItems: 'flex-start' }}>
              <span className={`dot s${eta ? 1 : 0}`} style={{ marginTop: 6 }} />
              <div className="grow"><b>{m.sender} → {m.recipient}</b> <span className="tag">{m.kind}</span><div className="muted" style={{ whiteSpace: 'pre-line' }}>{m.text.slice(0, 220)}</div></div>
              <span className="num dim">{eta ? `in ${eta}s` : 'delivered'}</span>
            </div>)
        })}{!data?.length && <p className="muted">No traffic yet.</p>}</div>
      </section>
    </div>
  )
}

function Emergencies({ ov }: { ov: MedicalOverview }) {
  return (
    <section className="card"><div className="head"><h2>Guided Response log</h2></div>
      {!ov.emergencies.length && <p className="muted">No emergencies yet. Hold the red button to run one.</p>}
      <div className="col" style={{ gap: 12 }}>{ov.emergencies.map(e => (
        <div key={e.id} className="card pad-sm">
          <div className="row"><b>{e.protocol ?? 'triage'}</b><span className="small muted">day {e.day} · {e.location}</span>
            {e.patient && <span className="row small" style={{ gap: 6 }}><Avatar initials={e.patient.toUpperCase()} />patient</span>}
            <span className="right small">{e.outcome ?? 'open'}</span></div>
          <div className="col small" style={{ gap: 2, marginTop: 8 }}>{e.log.map(([t, x], i) => <span key={i}><span className="num dim">{String(Math.floor(t / 60)).padStart(2, '0')}:{String(t % 60).padStart(2, '0')}</span> {x}</span>)}</div>
        </div>))}</div>
    </section>
  )
}
