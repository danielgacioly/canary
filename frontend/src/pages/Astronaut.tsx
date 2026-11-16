// A crew member's page. The crew sees only the public card: goal participation, never a status.
// Health details and operational status appear for the medical team only.
import { Link, Navigate, useParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { CrewDetail, Person } from '../api/types'
import BodyView, { RiskBlock } from '../components/BodyView'
import EvaReadiness from '../components/EvaReadiness'
import RadiationBar from '../components/RadiationBar'
import { Dot } from '../components/People'
import { Icon, Loading, Spark } from '../components/ui'
import { assessWord, fmtValue, missingNote, notAssessed, num } from '../lib/health'
import { ActionError } from '../components/Field'
import { useAction } from '../lib/useAction'
import { useApi, useSession, useSignedApi } from '../state/session'
import { useState } from 'react'
import RulesNote from '../components/RulesNote'

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
  const { data: o } = useSignedApi(() => api.overview(), [])
  if (error) return <div className="page"><p className="muted">{error}</p></div>
  if (!d) return <Loading what="crew member" />
  if (d === 'private') {
    const person = o?.people.find(p => p.id === id)
    return person ? <PublicCard p={person} /> : <Loading what="crew member" />
  }
  // Indicators never read in the window get no row of dashes: they are named once under the table.
  const all = Object.values(d.indicators)
  const read = all.filter(i => i.value !== null || (d.trends[i.id] ?? []).some(([, y]) => y !== null))
  const unread = all.filter(i => !read.includes(i))
  return (
    <div className="page">
      <Link to="/crew" className="back"><Icon name="back" />Crew</Link>
      <div className="head rise">
        <Dot p={d.crew} ops={d.ops} size="md" />
        <div><h1>{d.crew.name}</h1><p className="sub">{d.crew.role} · medical team view</p></div>
        {d.ops && <div className="right ops-right"><span className="small dim">Operational status</span>{notAssessed(d.assessment) ? <span className="status nodata"><span className="dot" />{assessWord(d.assessment)}</span> : <span className={`status s${d.ops.level}`}><span className="dot" />{d.ops.label}</span>}</div>}
      </div>
      <BodyView key={d.crew.id} d={d} self={false} />
      <section className="rise"><EvaReadiness d={d} self={false} /></section>
      <RisksAndCare d={d} />
      {d.access === 'medical' && <CorrectValue d={d} />}
      <section className="rise">
        <div className="section-head"><h2>All numbers</h2><span className="sub">last 30 days against their own normal</span></div>
        {read.length > 0 && (
          <div className="scroll"><table className="t">
            <thead><tr><th>Indicator</th><th>Now</th><th>Their normal</th><th>Last 30 days</th></tr></thead>
            <tbody>{read.map(i => (
              <tr key={i.id}>
                <td><b>{i.name}</b><div className="small dim">{i.area}</div></td>
                <td className="num">{fmtValue(i)} {i.value !== null && <span className="dim">{i.unit}</span>}{missingNote(i) && <div className="small dim">{missingNote(i)}</div>}</td>
                <td className="num muted">{num(i.baseline, i.dp)}</td>
                <td><Spark data={d.trends[i.id]} base={i.baseline ?? undefined} color={i.area === 'mental' ? 'var(--mental)' : 'var(--physical)'} w={120} h={28} /></td>
              </tr>))}</tbody>
          </table></div>
        )}
        {unread.length > 0 && <p className="small muted">No readings yet: {unread.map(i => i.name).join(', ')}.</p>}
      </section>
      <VitalsPhotos d={d} />
    </div>
  )
}

/** EDIT-01: the medical team corrects a value on record. The old value stays, with who changed it and why; open requests from the crew are listed here. */
function CorrectValue({ d }: { d: CrewDetail }) {
  const { bump, toast } = useSession()
  const open = useApi(() => api.corrections(), [d.crew.id])
  const first = d.crew.name.split(' ')[0]
  const [h, setH] = useState({ value: '', reason: '' })
  const [m, setM] = useState({ id: '', value: '', reason: '' })
  const saveH = useAction(), saveM = useAction()
  const hOk = Number(h.value) >= 140 && Number(h.value) <= 210 && h.reason.trim().length >= 3
  const mOk = Number.isInteger(Number(m.id)) && Number(m.id) > 0 && m.value.trim() !== '' && Number.isFinite(Number(m.value)) && m.reason.trim().length >= 3
  const requests = (open.data?.requests ?? []).filter(r => r.crew_id === d.crew.id)
  const FIELD: Record<string, string> = { height_cm: 'Height', mission_name: 'Mission name', measurement: 'Measurement' }
  return (
    <section className="rise">
      <div className="section-head"><h2>Correct a value</h2><span className="sub">The old value stays on record, with who changed it and why</span></div>
      <div className="grid g2">
        <form className="col correct-form" noValidate onSubmit={e => {
          e.preventDefault()
          if (hOk) saveH.run(async () => { await api.correctHeight(d.crew.id, Number(h.value), h.reason.trim()); setH({ value: '', reason: '' }); bump(); toast(`${first}'s height corrected`) })
        }}>
          <span className="lbl">Height (cm)</span>
          <input type="number" inputMode="decimal" min={140} max={210} aria-label="Corrected height in centimetres" value={h.value} onChange={e => setH({ ...h, value: e.target.value })} />
          <input aria-label="Why the height changes" maxLength={300} value={h.reason} onChange={e => setH({ ...h, reason: e.target.value })} placeholder="Why (3 to 300 characters)" />
          <ActionError error={saveH.error} />
          <button className="btn sm" disabled={!hOk || saveH.busy}>{saveH.busy ? 'Saving…' : 'Correct height'}</button>
        </form>
        <form className="col correct-form" noValidate onSubmit={e => {
          e.preventDefault()
          if (mOk) saveM.run(async () => { await api.correctMeasurement(Number(m.id), Number(m.value), m.reason.trim()); setM({ id: '', value: '', reason: '' }); bump(); toast('Measurement corrected') })
        }}>
          <span className="lbl">A measurement</span>
          <input type="number" inputMode="numeric" min={1} aria-label="Measurement id" value={m.id} onChange={e => setM({ ...m, id: e.target.value })} placeholder="Measurement id" />
          <input type="number" inputMode="decimal" aria-label="Corrected value" value={m.value} onChange={e => setM({ ...m, value: e.target.value })} placeholder="Corrected value" />
          <input aria-label="Why the measurement changes" maxLength={300} value={m.reason} onChange={e => setM({ ...m, reason: e.target.value })} placeholder="Why (3 to 300 characters)" />
          <ActionError error={saveM.error} />
          <button className="btn sm" disabled={!mOk || saveM.busy}>{saveM.busy ? 'Saving…' : 'Correct measurement'}</button>
        </form>
      </div>
      <div className="section-head" style={{ marginTop: 18 }}><h3>Open requests from {first}</h3></div>
      {requests.length ? (
        <ul className="plain correct-list">{requests.map(r => (
          <li key={r.id} className="small">
            <b>{FIELD[r.field] ?? r.field}</b>{r.target ? ` ${r.target}` : ''}{r.proposed !== null && r.proposed !== undefined ? <span> → {String(r.proposed)}</span> : null}
            <span className="muted"> · {r.reason}</span>
          </li>))}</ul>
      ) : <p className="small muted">{open.error ? 'Could not load the requests.' : `No open correction requests from ${first}.`}</p>}
    </section>
  )
}

/** The medical view of one person: every risk with its evidence and where the data comes from, the care windows, the career dose. */
function RisksAndCare({ d }: { d: CrewDetail }) {
  const raised = d.risks.filter(r => r.level > 0).sort((a, b) => b.level - a.level)
  const quiet = d.risks.filter(r => r.level === 0)
  return (
    <>
      <section className="rise">
        <div className="section-head"><h2>Risks</h2><span className="sub">with the evidence behind each one</span></div>
        {raised.length === 0 && <p className="muted">Nothing is raised.</p>}
        <div className="risk-list">{raised.map(r => <RiskBlock key={r.id} r={r} today={d.mission.day} />)}</div>
        {quiet.length > 0 && <p className="small dim">{raised.length ? 'Not raised' : 'Checked'}: {quiet.map(r => r.name).join(', ')}.</p>}
        <RulesNote review={d.rules_review} />
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
          {p.today.streak > 0 && <p className="small muted" style={{ marginTop: 10 }}>{p.today.streak}-day streak</p>}
        </div>
        <div className="detail-card rise gate-mini" style={{ ['--d' as string]: 2 }}>
          <span className="lock"><Icon name="lock" size={20} /></span>
          <h2>{first}'s health is private</h2>
          <p className="muted">The crew sees only {first}'s goals done. Numbers, alerts and operational status stay with {first} and the medical team.</p>
          <Link to="/medical" className="link">Medical team: open the console</Link>
        </div>
      </section>
    </div>
  )
}
