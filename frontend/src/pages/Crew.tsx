// Crew home: what everyone on board may see. The crew, today's hazards, crew missions.
// No status, no scores, no averages (with four people an average gives individuals away), no vitals.
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { TeamRow } from '../components/GoalItems'
import { Dot } from '../components/People'
import Hazards from '../components/Hazards'
import { Icon, Loading } from '../components/ui'
import { useApi, useSession } from '../state/session'

export default function Crew() {
  const { me, catalog } = useSession()
  const { data, error } = useApi(() => api.overview(), [])
  const { data: plan } = useApi(() => api.plan(), [])
  const nav = useNavigate()
  if (error) return <div className="page"><p className="muted">Cannot reach the Canary API. Is the backend running on port 8000?</p></div>
  if (!data || !catalog) return <Loading what="crew" />
  const n = data.people.length
  const storm = data.warnings[0]
  const names = Object.fromEntries(catalog.crew.map(c => [c.id, c.name]))
  const eva = storm ? { l: 2, t: 'EVA suspended for everyone' }
    : data.eva_open ? { l: 0, t: 'EVA open, the medical team clears each person' }
      : { l: 1, t: 'No EVA at this place' }
  const ms = data.mission
  const count = ['No one', 'One', 'Two', 'Three', 'Four', 'Five', 'Six'][n] ?? String(n)
  const last = plan ? plan.legs[plan.legs.length - 1].end : null
  const headline = ms.day < 0 ? `${count} in training, launch in ${-ms.day} ${ms.day === -1 ? 'day' : 'days'}`
    : last !== null && ms.day > last ? `${count} home, mission complete`
      : `${count} aboard${last !== null ? `, day ${ms.day} of ${last}` : ''}`

  return (
    <div className="page">
      <div className="head rise">
        <div>
          <h1>{headline}</h1>
          <p className="sub">{ms.day_label} · {ms.place.name}. No one's health is shown here; each person's status goes only to the medical team.</p>
        </div>
        <button className="btn right" onClick={() => nav('/today')}><Icon name={me ? 'open' : 'lock'} />{me ? 'Open my health' : 'Enter my space'}</button>
      </div>

      <section className="detail-card constellation rise" style={{ ['--d' as string]: 1 }}>
        <div className="orbit">
          {data.people.map((p, i) => (
            <button key={p.id} className="member rise" style={{ ['--d' as string]: i + 2 }} onClick={() => nav(p.id === me ? '/today' : `/crew/${p.id}`)}>
              <Dot p={p} size="xl" me={p.id === me} />
              <b>{p.name}</b>
              <span className="small muted">{p.role}</span>
              <span className="routine" title="Routine goals done today">
                <span className="bar-track"><i style={{ width: `${(100 * p.today.done) / Math.max(1, p.today.total)}%` }} /></span>
                <span className="small dim num">{p.today.done}/{p.today.total} today</span>
              </span>
              {(p.id === me || p.shared) && <span className="tag">{p.id === me ? 'You' : 'Shares data'}</span>}
            </button>
          ))}
        </div>
      </section>

      <section className="rise" style={{ ['--d' as string]: 2 }}>
        <div className="section-head">
          <h2>Hazards here today</h2>
          <span className="sub">NASA's five hazards of spaceflight, at {ms.place.name}. Tap one to see what it acts on.</span>
        </div>
        {data.warnings.map(w => (
          <div key={w.id} className={`warning s${w.level}`}>
            <span className="dot" />
            <div className="grow"><b>{w.title}</b><p className="small muted">{w.todo.join(' · ')}</p></div>
          </div>
        ))}
        <Hazards items={data.ridge} />
        <p className="facts-line small">
          <span><span className={`dot s${eva.l}`} />{eva.t}</span>
          <span>Mission dose {data.dose.mission_msv} mSv, {data.dose.pct_of_limit}% of the career limit</span>
          <span className="dim">Simulated, the same for everyone</span>
        </p>
      </section>

      <section className="rise" style={{ ['--d' as string]: 3 }}>
        <div className="section-head">
          <h2>Crew missions</h2>
          <span className="sub">{data.team_done} of {data.team_total} done this week · crew streak {data.crew_streak} {data.crew_streak === 1 ? 'day' : 'days'}</span>
          <button className="link right" onClick={() => nav('/ranking')}>Ranking</button>
        </div>
        <div className="team-grid">{data.team.map(t => <TeamRow key={t.id} t={t} names={names} />)}</div>
      </section>

      <details className="contract-box">
        <summary><Icon name="shield" size={16} />Who sees what<span className="small muted">Agreed by the crew on day 0</span></summary>
        <div className="scroll"><table className="t contract">
          <thead><tr><th>Information</th><th>The astronaut</th><th>Medical team</th><th>The crew</th><th>Earth</th></tr></thead>
          <tbody>{data.contract.map(r => (
            <tr key={r.info}><td><b>{r.info}</b></td>{[r.self, r.doctor, r.crew, r.earth].map((v, i) => <td key={i} className={v === 'No' ? 'dim' : ''}>{v}</td>)}</tr>
          ))}</tbody>
        </table></div>
      </details>
    </div>
  )
}
