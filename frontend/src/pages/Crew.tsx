// Crew home: what everyone on board may see. Participation, hazards, crew goals.
// No status, no scores, no averages (with four people an average gives individuals away), no vitals.
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { TeamRow } from '../components/GoalItems'
import { Dot } from '../components/People'
import { CountUp, Icon, Loading } from '../components/ui'
import { useApi, useSession } from '../state/session'

export default function Crew() {
  const { me, catalog } = useSession()
  const { data, error } = useApi(() => api.overview(), [])
  const { data: plan } = useApi(() => api.plan(), [])
  const nav = useNavigate()
  if (error) return <div className="page"><p className="muted">Cannot reach the Canary API. Is the backend running on port 8000?</p></div>
  if (!data || !catalog) return <Loading what="crew" />
  const n = data.people.length
  const storm = data.hazards.find(h => h.level === 2)
  const names = Object.fromEntries(catalog.crew.map(c => [c.id, c.name]))
  const eva = storm ? { l: 2, t: 'EVA suspended for everyone', s: storm.title }
    : data.eva_open ? { l: 0, t: 'EVA open', s: 'The medical team clears each person' }
      : { l: 1, t: 'No EVA at this place', s: 'The medical team clears each person' }
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
          <span className="eyebrow">{ms.day_label} · {ms.place.name}</span>
          <h1 style={{ marginTop: 6 }}>{headline}</h1>
          <p className="sub">No one's health is shown here. Each person's status goes only to the medical team.</p>
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
              <span className="small dim row" style={{ gap: 5 }}><Icon name={p.shared ? 'open' : 'lock'} size={13} />{p.id === me ? 'You' : p.shared ? 'Shares health with the crew' : 'Health private'}</span>
            </button>
          ))}
        </div>
      </section>

      <div className="stats">
        <div className={`stat rise s${eva.l}`} style={{ ['--d' as string]: 3 }}><div className="k">Outside activity</div><b className="c" style={{ fontSize: 22 }}>{eva.t}</b><div className="s">{eva.s}</div></div>
        <div className="stat rise" style={{ ['--d' as string]: 4 }}><div className="k">Crew streak</div><b className="num"><CountUp value={data.crew_streak} /><small>days</small></b><div className="s">Days when at least 3 of 4 kept their routine</div></div>
        <div className="stat rise" style={{ ['--d' as string]: 5 }}><div className="k">Crew missions</div><b className="num"><CountUp value={data.team_done} /><small>of {data.team_total}</small></b><div className="s">done this week</div></div>
        <div className="stat rise" style={{ ['--d' as string]: 6 }}><div className="k">Mission dose (simulated)</div><b className="num"><CountUp value={data.dose.mission_msv} dp={1} /><small>mSv</small></b><div className="s">{data.dose.pct_of_limit}% of the career limit · same for all</div></div>
      </div>

      <section className="grid g2">
        <div className="detail-card rise" style={{ ['--d' as string]: 7 }}>
          <div className="section-head"><h2>Hazards now</h2><span className="sub">The same for everyone on board</span></div>
          <div className="list">
            {data.hazards.map(h => (
              <div key={h.title} className="item" style={{ alignItems: 'flex-start' }}>
                <span className={`dot s${h.level}`} style={{ marginTop: 8 }} />
                <div className="grow"><b>{h.title}</b><div className="small muted">{h.what}</div></div>
              </div>
            ))}
          </div>
        </div>
        <div className="rise" style={{ ['--d' as string]: 8 }}>
          <div className="section-head"><h2>Crew missions</h2><span className="sub">This week, everyone earns the XP</span></div>
          <div className="col">{data.team.slice(0, 4).map(t => <TeamRow key={t.id} t={t} names={names} />)}</div>
          {data.team.length > 4 && <button className="link" style={{ marginTop: 12 }} onClick={() => nav('/ranking')}>All {data.team.length} crew missions</button>}
        </div>
      </section>

      <section className="detail-card rise" style={{ ['--d' as string]: 9 }}>
        <div className="section-head"><Icon name="shield" size={18} /><h2>Who sees what</h2><span className="sub">Agreed by the crew on day 0. Anyone can choose to share more.</span></div>
        <div className="scroll"><table className="t contract">
          <thead><tr><th>Information</th><th>The astronaut</th><th>Medical team</th><th>The crew</th><th>Earth</th></tr></thead>
          <tbody>{data.contract.map(r => (
            <tr key={r.info}><td><b>{r.info}</b></td>{[r.self, r.doctor, r.crew, r.earth].map((v, i) => <td key={i} className={v === 'No' ? 'dim' : ''}>{v}</td>)}</tr>
          ))}</tbody>
        </table></div>
      </section>
    </div>
  )
}
