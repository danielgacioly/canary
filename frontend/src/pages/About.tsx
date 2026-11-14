import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Icon } from '../components/ui'
import { useApi, useSession } from '../state/session'

export default function About() {
  const { catalog, setStep, toast } = useSession()
  const { data: st } = useApi(() => api.assistantStatus(), [])
  const nav = useNavigate()
  return (
    <div className="page" style={{ maxWidth: 1180 }}>
      <div className="head"><div><h1>A health watch-keeper for when Earth is too far to answer.</h1><p className="sub">About Canary, its data and how it is built</p></div>
        <div className="row right"><button className="btn" onClick={() => nav('/welcome')}>Replay intro</button>
          <button className="btn" onClick={async () => { await api.reset(); await setStep(0); toast('Demo reset. Mission setup starts again.') }}>Reset demo</button></div></div>

      <div className="grid g3">
        {[['Goals', 'Personal and crew goals for body and mind: exercise, water, sleep, meditation, reading, crew time, films, calls home. XP, levels, streaks and mission patches.'],
          ['Warnings', 'Each person against their own pre-flight normal, never an average. Signals are crossed (sleep + mood + focus) and every warning says what to do now.'],
          ['Guided Response', 'Hold the red button for one second. Ten situations, step by step, adapted to gravity and place, with timers, a CPR pacer, voice and a report for Earth.']].map(([h, p]) => (
          <div key={h} className="card"><h2>{h}</h2><p className="muted" style={{ marginTop: 8 }}>{p}</p></div>))}
      </div>

      <section className="card">
        <div className="head"><h2>NASA open data in Canary</h2></div>
        <div className="scroll"><table className="t"><thead><tr><th>Source</th><th>Provider</th><th>Used for</th></tr></thead>
          <tbody>{catalog?.sources.map(s => <tr key={s.id}><td><a href={s.url} target="_blank" rel="noreferrer" className="link">{s.name}</a></td><td className="muted">{s.org}</td><td>{s.used_for}</td></tr>)}</tbody></table></div>
        <p className="small dim" style={{ marginTop: 10 }}>Astronaut vital signs are not published as open data, so crew vitals, names and messages are simulated and labelled as such. Protocols are illustrative and not clinically reviewed.</p>
      </section>

      <div className="grid g2">
        <section className="card">
          <div className="head"><h2>How it is built</h2></div>
          <pre style={{ margin: 0, font: '500 12px/1.6 var(--f-mono)', color: 'var(--muted)', whiteSpace: 'pre' , overflowX: 'auto' }}>{`Web app (React + Three.js)
   │  HTTP /api
   ▼
Canary API (FastAPI, one process)
   ├─ telemetry   sensors → simulator today
   ├─ health      baseline, alerts, scores
   ├─ goals       XP, crew missions, patches
   ├─ protocols   Guided Response bank
   ├─ nasa        DONKI · RAD · OSD-569
   ├─ medical     PIN → short token
   └─ assistant   LLMProvider slot
   ▼
SQLite on board  ──later──▶  ground sync`}</pre>
        </section>
        <section className="card col">
          <div className="head"><h2>The AI slot</h2><span className="tag right">{st ? (st.configured ? st.provider : 'no model connected') : '…'}</span></div>
          <p className="muted">The assistant is designed, wired and testable; the model is the last piece. It explains and never diagnoses.</p>
          <ul className="steps">{st?.rules.map(r => <li key={r}>{r}</li>)}</ul>
          <span className="lbl" style={{ marginTop: 6 }}>Tools a model can call</span>
          <div className="row wrap" style={{ gap: 6 }}>{st?.tools.map(t => <span key={t.name} className="tag" title={t.description}>{t.name}</span>)}</div>
        </section>
      </div>

      <section className="card">
        <div className="head"><h2>Who pays for it</h2></div>
        <div className="grid g3">
          <div><b>Space agencies and commercial crews</b><p className="muted small" style={{ marginTop: 6 }}>Licence per mission and crew seat, with integration and protocol review.</p></div>
          <div><b>Analog missions and polar stations</b><p className="muted small" style={{ marginTop: 6 }}>A training edition for habitats and stations where isolation is the same problem.</p></div>
          <div><b>Remote work on Earth</b><p className="muted small" style={{ marginTop: 6 }}>Offshore platforms, ships, mines and remote communities: the hospital is far there too. The core stays open source.</p></div>
        </div>
      </section>
      <button className="btn pri" style={{ alignSelf: 'flex-start' }} onClick={() => nav('/today')}>Back to today<Icon name="chev" /></button>
    </div>
  )
}
