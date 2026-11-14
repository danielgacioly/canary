import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import AskCanary from '../features/AskCanary'
import GuidedResponse from '../features/GuidedResponse'
import { useApi, useSession } from '../state/session'
import { Avatar, CanaryMark, Icon } from './ui'

export default function Shell() {
  const { mission, catalog, me, setMe, emergency, setEmergency, askOpen, setAskOpen, toasts } = useSession()
  const [where, setWhere] = useState(false)
  const nav = useNavigate()
  const { data: crew } = useApi(() => api.crew(), [])
  const meInfo = catalog?.crew.find(c => c.id === me)
  const meSummary = crew?.crew.find(c => c.id === me)

  useEffect(() => { if (!me) nav('/welcome') }, [me, nav])

  const links = [
    { to: '/me', icon: 'me', label: 'My health', badge: meSummary && meSummary.level ? meSummary.alerts : 0, lvl: meSummary?.level ?? 0 },
    { to: '/crew', icon: 'crew', label: 'Crew' },
    { to: '/goals', icon: 'goals', label: 'Goals' },
    { to: '/ranking', icon: 'rank', label: 'Ranking' },
    { to: '/mission', icon: 'mission', label: 'Mission' },
  ]
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand"><CanaryMark /><div><b>CANARY</b><small>CREW HEALTH SYSTEM</small></div></div>
        {links.map(l => (
          <NavLink key={l.to} to={l.to} className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}>
            <Icon name={l.icon} /><span>{l.label}</span>
            {!!l.badge && <span className={`badge s${l.lvl}`}>{l.badge}</span>}
          </NavLink>
        ))}
        <div className="sep" />
        <NavLink to="/medical" className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}><Icon name="med" /><span>Medical console</span></NavLink>
        <NavLink to="/about" className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}><Icon name="info" /><span>About & data</span></NavLink>
        <div className="foot">
          {meInfo && (
            <button className="me-chip" onClick={() => { setMe(null); nav('/welcome?pick=1') }} title="Switch crew member on this terminal">
              <Avatar initials={meInfo.initials} />
              <span className="grow"><b style={{ display: 'block', fontSize: 13 }}>{meInfo.name}</b><span className="lbl">{meInfo.role}</span></span>
            </button>
          )}
          <p className="small dim" style={{ marginTop: 10 }}>No accounts on board. This terminal is set to one crew member.</p>
        </div>
      </aside>

      <div className="main">
        <header className="top">
          {mission && (
            <div className="clock">
              <div className="k"><span className="lbl">Mission time</span><b>{mission.day_label}</b></div>
              <span className="vsep" />
              <button className="k" onClick={() => setWhere(true)} style={{ textAlign: 'left' }} title="Change where you are">
                <span className="lbl">Where you are ▾</span><b style={{ color: 'var(--cyan)' }}>{mission.place.name}</b>
              </button>
              <span className="vsep opt" />
              <div className="k opt"><span className="lbl">Gravity</span><b>{mission.place.gravity}</b></div>
              <div className="k opt"><span className="lbl">Earth replies in</span><b>{mission.place.reply}</b></div>
              {crew && <div className={`k opt s${crew.space_weather.active ? 2 : 0}`}><span className="lbl">Space weather</span><b className="c">{crew.space_weather.active ? 'Storm' : 'Calm'}</b></div>}
            </div>
          )}
          <div className="right row">
            <button className="btn sm" onClick={() => setAskOpen(true)}><Icon name="ask" size={15} />Ask Canary</button>
            <HoldButton onFire={() => setEmergency(true)} />
          </div>
        </header>
        <Outlet />
      </div>

      <StoryBar />
      {where && <WherePicker onClose={() => setWhere(false)} />}
      {emergency && <GuidedResponse onClose={() => setEmergency(false)} />}
      {askOpen && <AskCanary onClose={() => setAskOpen(false)} />}
      <div className="toasts">{toasts.map(t => <div key={t.id} className="toast">{t.t}</div>)}</div>
    </div>
  )
}

/** Hold for one second: easy to reach, hard to press by accident. */
export function HoldButton({ onFire, label = 'Hold for emergency' }: { onFire: () => void; label?: string }) {
  const [hold, setHold] = useState(false)
  const t = useRef<number>()
  const start = () => { setHold(true); t.current = window.setTimeout(() => { setHold(false); onFire() }, 1000) }
  const stop = () => { setHold(false); clearTimeout(t.current) }
  return (
    <button className={`sos ${hold ? 'hold' : ''}`} onPointerDown={start} onPointerUp={stop} onPointerLeave={stop}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onFire() } }} aria-label="Emergency: hold for one second">
      <i className="ring" /><span>{label}</span>
    </button>
  )
}

function StoryBar() {
  const { mission, setStep, catalog } = useSession()
  const [busy, setBusy] = useState(false)
  if (!mission || !catalog) return null
  const go = async (i: number) => { setBusy(true); try { await setStep(i) } finally { setBusy(false) } }
  return (
    <div className="story">
      <span className="lbl" style={{ color: 'var(--gold)' }}>Demo story {mission.step + 1}/{mission.steps}</span>
      <div className="dots">{catalog.story.map((_, i) => <button key={i} className={i === mission.step ? 'on' : ''} onClick={() => go(i)} aria-label={`Story step ${i + 1}`} disabled={busy} />)}</div>
      <p className="grow"><b style={{ color: 'var(--ink)' }}>{mission.story.when}.</b> {mission.story.text}</p>
      <button className="btn sm" disabled={busy || mission.step === 0} onClick={() => go(mission.step - 1)}><Icon name="back" size={14} /></button>
      <button className="btn sm pri" disabled={busy || mission.step === mission.steps - 1} onClick={() => go(mission.step + 1)}>Next<Icon name="chev" size={14} /></button>
    </div>
  )
}

function WherePicker({ onClose }: { onClose: () => void }) {
  const { catalog, mission, setLocation, toast } = useSession()
  if (!catalog || !mission) return null
  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal wide" onClick={e => e.stopPropagation()}>
        <div className="row" style={{ marginBottom: 6 }}><h2>Where are you?</h2><button className="btn sm ghost right" onClick={onClose}><Icon name="close" size={15} /></button></div>
        <p className="muted" style={{ marginBottom: 16 }}>The place changes the goals, the alerts and every step of Guided Response.</p>
        <div className="places">
          {Object.entries(catalog.locations).map(([k, p]) => (
            <button key={k} className={`place ${mission.location === k ? 'on' : ''}`} onClick={async () => { await setLocation(k); toast(`Now at: ${p.name}`); onClose() }}>
              <span className="lbl">{p.sub}</span><b style={{ fontSize: 17 }}>{p.name}</b>
              <dl><dt>Gravity</dt><dd>{p.gravity}</dd><dt>Earth replies</dt><dd>{p.reply}</dd><dt>Hospital</dt><dd>{p.hospital}</dd><dt>Radiation</dt><dd>{p.dose_rate} mSv/day</dd></dl>
              <span className="small muted">{p.what}</span>
            </button>
          ))}
        </div>
        <p className="small dim" style={{ marginTop: 14 }}>Daily doses are typical published orders of magnitude, to be verified. The demo story resets the place on each step.</p>
      </div>
    </div>
  )
}
