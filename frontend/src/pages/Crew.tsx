// Crew home: what everyone on board may see. The crew, today's hazards, crew missions.
// No status, no scores, no averages (with few people an average gives individuals away), no vitals.
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { TeamRow } from '../components/GoalItems'
import { Dot } from '../components/People'
import Hazards from '../components/Hazards'
import { Loading } from '../components/ui'
import { protocolPath } from './Protocols'
import { useApi, useSession, useSignedApi } from '../state/session'

export default function Crew() {
  const { me, catalog } = useSession()
  const { data, error, locked } = useSignedApi(() => api.overview(), [])
  if (locked) return <div className="page"><p className="waiting">Sign in to your space to see the crew.</p></div>
  const { data: plan } = useApi(() => api.plan(), [])
  const nav = useNavigate()
  if (error) return <div className="page"><p className="muted">Canary is not reachable. Check the connection to the ship's server.</p></div>
  if (!data || !catalog) return <Loading what="crew" />
  const n = data.people.length
  if (n === 0) return <div className="page"><p className="waiting">No one is registered on this terminal. Mission Control registers the crew.</p></div>
  const ms = data.mission
  const count = ['No one', 'One', 'Two', 'Three', 'Four', 'Five', 'Six'][n] ?? String(n)
  const last = plan ? plan.legs[plan.legs.length - 1].end : null
  const headline = ms.day < 0 ? `${count} in training, launch in ${-ms.day} ${ms.day === -1 ? 'day' : 'days'}`
    : last !== null && ms.day > last ? `${count} home, mission complete`
      : `${count} aboard${last !== null ? `, day ${ms.day} of ${last}` : ''}`

  return (
    <div className="page">
      <div className="head rise">
        <div><h1>{headline}</h1></div>
      </div>

      <section data-tour="crew-home" className="detail-card constellation rise" style={{ ['--d' as string]: 1 }}>
        <div className="orbit">
          {data.people.map((p, i) => (
            <button key={p.id} className="member rise" style={{ ['--d' as string]: i + 2 }} aria-label={`Open ${p.name}'s space`}
              onClick={() => nav(p.id === me ? '/me' : `/me?who=${p.id}`)}>
              <Dot p={p} size="xl" me={p.id === me} />
              <b>{p.name}</b>
              <span className="small muted">{p.role}</span>
              <span className="routine" title="Routine goals done today">
                <span className="bar-track"><i style={{ width: `${(100 * p.today.done) / Math.max(1, p.today.total)}%` }} /></span>
                <span className="small dim num">{p.today.done}/{p.today.total} routine goals</span>
              </span>
            </button>
          ))}
        </div>
      </section>

      <section data-tour="hazards" className="rise" style={{ ['--d' as string]: 2 }}>
        <div className="section-head">
          <h2>Hazards at {ms.place.name}</h2>
          <span className="sub">Tap one to see what it affects.</span>
        </div>
        {data.warnings.map(w => (
          <div key={w.id} className={`warning s${w.level}`}>
            <span className="dot" />
            <div className="grow row"><b>{w.title}</b><Link className="link right" to={protocolPath(w.protocol ?? 'rad')}>Protocol</Link></div>
          </div>
        ))}
        <Hazards items={data.ridge} />
      </section>

      <section className="rise" style={{ ['--d' as string]: 3 }}>
        <div className="section-head">
          <h2>Crew missions</h2>
          <span className="sub">{data.team_done} of {data.team_total} done this week{data.crew_streak > 0 && ` · ${data.crew_streak}-day crew streak`}</span>
          <button className="link right" onClick={() => nav('/ranking')}>Ranking</button>
        </div>
        <div className="team-grid">{data.team.map(t => <TeamRow key={t.id} t={t} />)}</div>
      </section>
    </div>
  )
}
