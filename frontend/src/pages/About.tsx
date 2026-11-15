import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Icon } from '../components/ui'
import { useApi, useSession } from '../state/session'

export default function About() {
  const { catalog } = useSession()
  const { data: st } = useApi(() => api.assistantStatus(), [])
  const nav = useNavigate()
  return (
    <div className="page about">
      <div className="head"><div><h1>A health watch-keeper for when Earth is too far to answer.</h1><p className="sub">About Canary, its data and how it is built</p></div>
      </div>

      <div className="about-cols">
        {[['Goals', 'Personal and crew goals for body and mind: exercise, water, sleep, meditation, reading, crew time, films, calls home. Streaks and mission patches.'],
          ['Warnings', 'Each person against their own pre-flight normal, never an average. Signals are crossed (sleep + mood + focus) and every warning says what to do now.'],
          ['Guided Response', 'Hold the red button for one second. Ten situations, step by step, adapted to gravity and place, with timers, a CPR pacer, voice and a report for Earth.']].map(([h, p]) => (
          <div key={h}><h2>{h}</h2><p className="muted">{p}</p></div>))}
      </div>

      <section>
        <div className="head"><h2>NASA open data in Canary</h2></div>
        <div className="scroll"><table className="t"><thead><tr><th>Source</th><th>Provider</th><th>Used for</th></tr></thead>
          <tbody>{catalog?.sources.map(s => <tr key={s.id}><td><a href={s.url} target="_blank" rel="noreferrer" className="link">{s.name}</a></td><td className="muted">{s.org}</td><td>{s.used_for}</td></tr>)}</tbody></table></div>
        <p className="small muted">3D anatomy: BodyParts3D, © The Database Center for Life Science (CC BY-SA 2.1 Japan).</p>
        <p className="small dim about-note">Astronaut vital signs are not published as open data, so crew vitals, names and messages are simulated and labelled as such. Protocols are illustrative and not clinically reviewed.</p>
      </section>

      <div className="about-pair">
        <section className="col">
          <div className="head"><h2>The AI slot</h2><span className="tag right">{st ? (st.configured ? st.provider : 'no model connected') : '…'}</span></div>
          <p className="muted">The assistant is designed, wired and testable; the model is the last piece. It explains and never diagnoses.</p>
          <ul className="steps">{st?.rules.map(r => <li key={r}>{r}</li>)}</ul>
          <span className="lbl about-tools-lbl">Tools a model can call</span>
          <div className="row wrap about-tools">{st?.tools.map(t => <span key={t.name} className="tag" title={t.description}>{t.name}</span>)}</div>
        </section>
      </div>

      <button className="btn pri about-back" onClick={() => nav('/crew')}>Back to the crew<Icon name="chev" /></button>
    </div>
  )
}
