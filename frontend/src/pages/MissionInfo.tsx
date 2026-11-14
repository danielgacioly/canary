// The mission and the crew as a whole: what anyone on board may read. No health data.
// From here, "Switch to Mission Control mode" shows the other side of the system.
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { MissionOverview } from '../api/types'
import { Dot } from '../components/People'
import Timeline from '../components/Timeline'
import { Icon, Loading } from '../components/ui'
import { useApi, useSession } from '../state/session'

const fmtDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-US', { day: 'numeric', month: 'long', year: 'numeric' })

export default function MissionInfo() {
  const { catalog } = useSession()
  const { data: o } = useApi<MissionOverview>(() => api.missionOverview(), [])
  const nav = useNavigate()
  if (!o || !catalog) return <Loading what="mission" />
  const ms = o.mission
  return (
    <div className="page mission-info">
      <div className="head rise">
        <div>
          <h1>{o.callsign ?? 'No mission'}</h1>
          <p className="sub">{o.name} · {o.crew.length} crew · registered by Mission Control</p>
        </div>
        <button className="btn ctl-switch right" onClick={() => nav('/control')}><Icon name="link" />Switch to Mission Control mode</button>
      </div>

      <div className="stats rise" style={{ ['--d' as string]: 1 }}>
        <div className="stat"><div className="k">Launch</div><b style={{ fontSize: 18 }}>{fmtDate(o.launch_date)}</b><div className="s">Day 0</div></div>
        <div className="stat"><div className="k">Today</div><b style={{ fontSize: 18 }}>{ms.day_label}</b><div className="s">{fmtDate(o.today_date)}</div></div>
        <div className="stat"><div className="k">Destination</div><b style={{ fontSize: 18 }}>{o.destination}</b><div className="s">{o.flight_days} days from launch to the end of the plan</div></div>
        <div className="stat"><div className="k">Where now</div><b style={{ fontSize: 18 }}>{ms.place.name}</b><div className="s">Earth replies {ms.place.reply === 'Live' ? 'live' : `in ${ms.place.reply}`}</div></div>
      </div>

      <section className="rise" style={{ ['--d' as string]: 2 }}>
        <div className="section-head"><h2>The crew</h2><span className="sub">Who they are. Their health stays with each of them and the medical team.</span></div>
        <div className="crew-cards">
          {o.crew.map(c => (
            <div key={c.id} className="crew-card">
              <Dot p={c} size="lg" />
              <div className="col" style={{ gap: 2 }}>
                <b>{c.name}</b>
                <span className="muted small">{c.role}</span>
              </div>
              <dl>
                <dt>Agency</dt><dd>{c.agency || '—'}</dd>
                <dt>From</dt><dd>{c.home}{c.nationality ? ` · ${c.nationality}` : ''}</dd>
                <dt>Speaks</dt><dd>{c.languages?.join(', ') || '—'}</dd>
                <dt>Before this</dt><dd>{c.flights ? `${c.flights} ${c.flights === 1 ? 'flight' : 'flights'}, ${c.days_in_space} days in space` : 'First flight'}</dd>
              </dl>
            </div>
          ))}
        </div>
      </section>

      <section className="rise" style={{ ['--d' as string]: 3 }}>
        <div className="section-head"><h2>Itinerary</h2><span className="sub">Health conditions for each leg are on the Mission plan page</span><button className="link right" onClick={() => nav('/plan')}>Mission plan</button></div>
        <Timeline legs={o.legs} places={catalog.locations} now={ms.day} nowLabel={ms.day_label} />
      </section>
    </div>
  )
}

/** Shown on every crew screen while Mission Control has not registered a crew and a mission. */
export function WaitingForControl() {
  const nav = useNavigate()
  return (
    <div className="page picker">
      <span className="lock rise"><Icon name="link" size={22} /></span>
      <h1 className="rise">Waiting for Mission Control</h1>
      <p className="muted rise" style={{ maxWidth: '52ch' }}>No crew and no mission are registered on this terminal yet. Mission Control registers the astronauts and the mission; nobody creates an account on board.</p>
      <button className="btn pri rise" onClick={() => nav('/control')}>Switch to Mission Control mode</button>
    </div>
  )
}
