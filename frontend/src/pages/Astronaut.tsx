// A crew member's page. The crew sees only the public card: goal participation, never a status.
// Health details and operational status appear for the medical team only.
import { Link, Navigate, useParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { CrewDetail, Person } from '../api/types'
import BodyView, { RiskBlock } from '../components/BodyView'
import EvaReadiness from '../components/EvaReadiness'
import RadiationBar from '../components/RadiationBar'
import { Dot } from '../components/People'
import { Icon, Loading, Patch, Spark } from '../components/ui'
import { fmtValue, missingNote, num } from '../lib/health'
import { ActionError } from '../components/Field'
import { useAction } from '../lib/useAction'
import { useApi, useSession } from '../state/session'
import { useState } from 'react'

export default function Astronaut() {
  const { id = '' } = useParams()
  const { me } = useSession()
  if (id === me) return <Navigate to="/me" replace />
  return <Other id={id} />
}

function Other({ id }: { id: string }) {
  const { data: d, error } = useApi<CrewDetail | 'private'>(() => api.crewDetail(id).catch(e => {
    if (e instanceof ApiError && e.status === 403) return 'private' as const
    throw e
  }), [id])
  const { data: o } = useApi(() => api.overview(), [])
  if (error) return <div className="page"><p className="muted">{error}</p></div>
  if (!d) return <Loading what="crew member" />
  if (d === 'private') {
    const person = o?.people.find(p => p.id === id)
    return person ? <PublicCard p={person} /> : <Loading what="crew member" />
  }
  const p = d.profile
  return (
    <div className="page">
      <Link to="/crew" className="back"><Icon name="back" />Crew</Link>
      <div className="head rise">
        <Dot p={d.crew} ops={d.ops} size="md" />
        <div><h1>{d.crew.name}</h1><p className="sub">{d.crew.role} · {d.crew.home} · {p.goals_week} goals this week · {p.badges_earned} patches</p></div>
        {d.ops && <div className="right ops-right"><span className="small dim">Operational status</span><span className={`status s${d.ops.level}`}><span className="dot" />{d.ops.label}</span></div>}
      </div>
      <p className="muted rise med-note"><b>Medical team view.</b> Everything about {d.crew.name.split(' ')[0]}, including alerts and advice.</p>
      <BodyView key={d.crew.id} d={d} self={false} />
      <section className="rise"><EvaReadiness d={d} self={false} /></section>
      <RisksAndCare d={d} />
      <section className="rise">
        <div className="section-head"><h2>All numbers</h2><span className="sub">last 30 days against their own normal</span></div>
        <div className="scroll"><table className="t">
          <thead><tr><th>Indicator</th><th>Now</th><th>Their normal</th><th>Last 30 days</th></tr></thead>
          <tbody>{Object.values(d.indicators).map(i => (
            <tr key={i.id}>
              <td><b>{i.name}</b><div className="small dim">{i.area}</div></td>
              <td className="num">{fmtValue(i)} {i.value !== null && <span className="dim">{i.unit}</span>}{missingNote(i) && <div className="small dim">{missingNote(i)}</div>}</td>
              <td className="num muted">{num(i.baseline, i.dp)}</td>
              <td><Spark data={d.trends[i.id]} base={i.baseline ?? undefined} color={i.area === 'mental' ? 'var(--mental)' : 'var(--physical)'} w={120} h={28} /></td>
            </tr>))}</tbody>
        </table></div>
      </section>
      <VitalsPhotos d={d} />
      <section>
        <div className="section-head"><h2>Patches</h2></div>
        <div className="patches">{p.badges.map(b => (
          <div key={b.id} className={`patch ${b.earned ? '' : 'off'}`}><Patch id={b.id} earned={b.earned} /><b>{b.name}</b><span className="small muted">{b.desc}</span></div>))}</div>
      </section>
    </div>
  )
}

/** Photos of the display kept with recent vitals check-ins: the person and the medical team only. */
/** The medical view of one person: every risk with its evidence and where the data comes from, the care windows, the career dose. */
function RisksAndCare({ d }: { d: CrewDetail }) {
  const raised = d.risks.filter(r => r.level > 0).sort((a, b) => b.level - a.level)
  const quiet = d.risks.filter(r => r.level === 0)
  return (
    <>
      <section className="rise">
        <div className="section-head"><h2>Risks</h2><span className="sub">with the evidence behind each one</span></div>
        {raised.length === 0 && <p className="muted">Nothing is raised.</p>}
        <div className="risk-list">{raised.map(r => <RiskBlock key={r.id} r={r} />)}</div>
        {quiet.length > 0 && <p className="small dim">{raised.length ? 'Not raised' : 'Checked'}: {quiet.map(r => r.name).join(', ')}.</p>}
      </section>
      {d.care_events.length > 0 && (
        <section className="rise">
          <div className="section-head"><h2>Care after emergencies</h2></div>
          <ul className="plain care-events">
            {d.care_events.map(e => (
              <li key={e.emergency_id}>
                <b>{e.name}</b>
                <span className="muted">{e.outcome}, day {e.day}</span>
                <span className="small num">{e.ops === 'rest' ? 'Rest' : e.ops === 'limited' ? 'Limited duty' : 'Full duty'} until day {e.until_day}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="rise">
        <div className="section-head"><h2>Career radiation dose</h2></div>
        <RadiationBar d={d} />
      </section>
    </>
  )
}

function VitalsPhotos({ d }: { d: CrewDetail }) {
  const rows = d.events.filter(e => e.kind === 'vitals' && e.has_photo)
  const [shown, setShown] = useState<{ id: number; url: string } | null>(null)
  const load = useAction()
  if (!rows.length) return null
  return (
    <section>
      <div className="section-head"><h2>Vital signs photos</h2><span className="sub">kept as evidence; the numbers typed are what counts</span></div>
      <ul className="plain recent">
        {rows.map(e => (
          <li key={e.id}>
            <b>Vital signs</b>
            <span className="muted">Photo of the display</span>
            <span className="dim small num">day {e.day} · <button type="button" className="link-btn" disabled={load.busy} onClick={() => shown?.id === e.id ? setShown(null) : load.run(async () => setShown({ id: e.id, url: (await api.checkinPhoto(d.crew.id, e.id)).data_url }))}>{shown?.id === e.id ? 'Hide photo' : 'Photo'}</button></span>
            {shown?.id === e.id && <img className="recent-photo" src={shown.url} alt={`Photo of the display, day ${e.day}`} />}
          </li>
        ))}
      </ul>
      <ActionError error={load.error} />
    </section>
  )
}

function PublicCard({ p }: { p: Person }) {
  const first = p.name.split(' ')[0]
  return (
    <div className="page">
      <Link to="/crew" className="back"><Icon name="back" />Crew</Link>
      <section className="detail-card public rise">
        <Dot p={p} size="xl" />
        <div className="col" style={{ gap: 6 }}>
          <h1>{p.name}</h1>
          <p className="muted">{p.role} · {p.home}</p>
        </div>
      </section>
      <section className="grid g2">
        <div className="detail-card rise" style={{ ['--d' as string]: 1 }}>
          <h2>Today's routine</h2>
          <div className="big-num num" style={{ margin: '10px 0' }}>{p.today.done}<small>of {p.today.total} goals</small></div>
          <div className="bar-track"><i style={{ width: `${(100 * p.today.done) / Math.max(1, p.today.total)}%` }} /></div>
          <p className="small muted" style={{ marginTop: 10 }}>{p.today.streak ? `${p.today.streak}-day streak.` : 'No streak running.'} Participation is shared; results are not.</p>
        </div>
        <div className="detail-card rise gate-mini" style={{ ['--d' as string]: 2 }}>
          <span className="lock"><Icon name="lock" size={20} /></span>
          <h2>{first}'s health is private</h2>
          <p className="muted">The crew sees only how {first} is doing with goals, nothing more. Numbers, alerts, advice and operational status stay with {first} and the medical team.</p>
          <Link to="/medical" className="link">Medical team: open the console</Link>
        </div>
      </section>
    </div>
  )
}
