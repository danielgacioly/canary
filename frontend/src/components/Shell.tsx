import { useRef, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAction } from '../lib/useAction'
import { ActionError } from './Field'
import AskCanary from '../features/AskCanary'
import GuidedResponse from '../features/GuidedResponse'
import { useApi, useSession } from '../state/session'
import { WaitingForControl } from '../pages/MissionInfo'
import { CrewDots, Dot } from './People'
import { CanaryMark, Icon } from './ui'

// Crew first: the system always opens on the whole crew. Personal data sits behind "Your health".
const NAV: { group: string; items: [string, string, string][] }[] = [
  { group: 'Crew', items: [['/crew', 'crew', 'Crew'], ['/tests', 'test', 'Tests'], ['/plan', 'plan', 'Mission plan'], ['/ranking', 'rank', 'Ranking']] },
  { group: 'Your health', items: [['/me', 'today', 'My space']] },
]

export default function Shell() {
  const { mission, me, emergency, setEmergency, askOpen, setAskOpen, toasts, prefs } = useSession()
  const [where, setWhere] = useState(false)
  const nav = useNavigate()
  const { data: crew } = useApi(() => api.overview(), [])
  const mine = crew?.people.find(c => c.id === me)

  return (
    <div className="shell">
      <aside className="side">
        <NavLink to="/crew" className="brand"><CanaryMark />CANARY</NavLink>
        {NAV.map(g => (
          <div key={g.group}>
            <div className="group">{g.group}</div>
            {g.items.map(([to, icon, label]) => (
              <NavLink key={to} to={to} className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}>
                <Icon name={icon} /><span>{label}</span>
                {to === '/me' && !me && <span className="count" style={{ color: 'var(--dim)' }}><Icon name="lock" size={13} /></span>}
              </NavLink>
            ))}
          </div>
        ))}
        <div className="group">Support</div>
        <button className="nav" onClick={() => setAskOpen(true)}><Icon name="ask" /><span>Ask Canary</span></button>
        <NavLink to="/medical" className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}><Icon name="med" /><span>Medical console</span></NavLink>
        <NavLink to="/settings" className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}><Icon name="gear" /><span>Settings</span></NavLink>
        <NavLink to="/about" className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}><Icon name="info" /><span>About & data</span></NavLink>
        <div className="foot"><ProfileChip mine={mine} /></div>
      </aside>

      <div className="main">
        <header className="topbar">
          {mission && (
            <>
              <button className="fact" onClick={() => setWhere(true)} title="Change where you are">
                <span>Where you are</span><b>{mission.place.name} ▾</b>
              </button>
              <div className="fact"><span>Mission time</span><b className="num">{mission.day_label}</b></div>
              <div className="fact opt"><span>Earth replies</span><b>{mission.place.reply}</b></div>
              {crew?.space_weather.active && <span className="storm-chip s2"><span className="dot" />Solar storm</span>}
            </>
          )}
          <div className="right row" style={{ gap: 14 }}>{mission?.callsign && <button className="mission-chip" onClick={() => nav('/mission')} title="The mission and the crew">{mission.callsign}</button>}{crew && <CrewDots people={crew.people} />}<HoldButton onFire={() => setEmergency(true)} /></div>
        </header>
        {mission && !mission.registered ? <WaitingForControl /> : <Outlet />}
      </div>

      {prefs.storyBar && mission?.registered && <StoryBar />}
      {where && <WherePicker onClose={() => setWhere(false)} />}
      {emergency && <GuidedResponse onClose={() => setEmergency(false)} />}
      {askOpen && <AskCanary onClose={() => setAskOpen(false)} />}
      <div className="toasts">{toasts.map(t => <div key={t.id} className="toast">{t.t}</div>)}</div>
    </div>
  )
}

/** Hold for one second: easy to reach, hard to press by accident. */
export function HoldButton({ onFire }: { onFire: () => void }) {
  const [hold, setHold] = useState(false)
  const t = useRef<number>()
  const start = () => { setHold(true); t.current = window.setTimeout(() => { setHold(false); onFire() }, 1000) }
  const stop = () => { setHold(false); clearTimeout(t.current) }
  return (
    <button className={`sos ${hold ? 'hold' : ''}`} onPointerDown={start} onPointerUp={stop} onPointerLeave={stop}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onFire() } }} aria-label="Emergency: hold for one second">
      <i className="ring" /><span>{hold ? 'Keep holding…' : 'Hold for emergency'}</span>
    </button>
  )
}

function StoryBar() {
  const { mission, setStep, catalog, me } = useSession()
  const nav = useNavigate()
  const move = useAction('toast')
  const busy = move.busy
  if (!mission || !catalog) return null
  const go = (i: number) => { move.run(() => setStep(i)) }
  return (
    <div className="story">
      <span className="small story-step">Demo {mission.step + 1}/{mission.steps}</span>
      <div className="dots">{catalog.story.map((_, i) => <button key={i} className={i === mission.step && !mission.custom_day ? 'on' : ''} onClick={() => go(i)} aria-label={`Story step ${i + 1}`} disabled={busy} />)}</div>
      <p className="grow">{mission.custom_day ? <><b className="ink">Free navigation.</b> You picked day {mission.day} on the mission plan. Press a dot to return to the story.</> : <><b className="ink">{mission.story.when}.</b> {mission.story.text}</>}</p>
      {!mission.custom_day && me !== mission.suggested_user && (
        <button className="btn sm ghost" onClick={() => nav(`/me?who=${mission.suggested_user}`)} title="Opens the PIN pad for this person">
          Enter as {catalog.crew.find(c => c.id === mission.suggested_user)?.name.split(' ')[0]}
        </button>
      )}
      <button className="btn sm ghost" disabled={busy || mission.step === 0} onClick={() => go(mission.step - 1)} aria-label="Previous step"><Icon name="back" /></button>
      <button className="btn sm" disabled={busy || mission.step === mission.steps - 1} onClick={() => go(mission.step + 1)}>Next<Icon name="chev" /></button>
    </div>
  )
}

function WherePicker({ onClose }: { onClose: () => void }) {
  const { mission, setLocation, toast } = useSession()
  const nav = useNavigate()
  const pick = useAction()
  if (!mission) return null
  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal wide" onClick={e => e.stopPropagation()}>
        <div className="row"><h2>Where are you?</h2><button className="btn sm ghost right" onClick={onClose} aria-label="Close"><Icon name="close" /></button></div>
        <p className="muted place-lead">
          The mission plan puts you at <b className="ink">{mission.leg.label || mission.leg.location}</b> today. Pick another place to simulate it, or <button className="link" onClick={() => { onClose(); nav('/plan') }}>edit the mission plan</button>.
        </p>
        <PlaceGrid current={mission.location} onPick={(k, name) => { pick.run(async () => { await setLocation(k); toast(`Simulating: ${name}`); onClose() }) }} />
        <ActionError error={pick.error} />
        {mission.location_override && <button className="btn" style={{ marginTop: 16 }} disabled={pick.busy} onClick={() => pick.run(async () => { await setLocation(null); onClose() })}>Back to the mission plan</button>}
      </div>
    </div>
  )
}

export function PlaceGrid({ onPick, current }: { onPick: (k: string, name: string) => void; current: string }) {
  const { catalog } = useSession()
  if (!catalog) return null
  return (
    <div className="places">
      {Object.entries(catalog.locations).map(([k, p], i) => (
        <button key={k} className={`place rise p-${k} ${current === k ? 'on' : ''}`} style={{ ['--d' as string]: i }} onClick={() => onPick(k, p.name)}>
          <div><h3 className="row" style={{ gap: 8 }}><span className="pc-dot" />{p.name}</h3><span className="small muted">{p.sub}</span></div>
          <dl><dt>Gravity</dt><dd>{p.gravity}</dd><dt>Earth replies</dt><dd>{p.reply}</dd><dt>Hospital</dt><dd>{p.hospital}</dd><dt>Radiation</dt><dd>{p.dose_rate} mSv/day</dd></dl>
          <span className="small muted">{p.what}</span>
        </button>
      ))}
    </div>
  )
}

/** Your profile at the foot of the sidebar. Signed in, it opens a small menu with Lock. */
function ProfileChip({ mine }: { mine?: { id: string; initials: string; name: string } }) {
  const { setMe } = useSession()
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  if (!mine) {
    return (
      <button className="me-chip" onClick={() => nav('/me')} title="My space">
        <span className="pdot sm"><Icon name="lock" /></span>
        <span className="grow"><b className="who-name">My space</b><span className="small muted">Choose your profile</span></span>
      </button>
    )
  }
  return (
    <div className="chip-wrap" onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setOpen(false) }}>
      {open && (
        <div className="chip-menu" role="menu">
          <button role="menuitem" onClick={() => { setOpen(false); nav('/me') }}><Icon name="today" />Open my space</button>
          <button role="menuitem" onClick={() => { setOpen(false); nav('/me/settings') }}><Icon name="gear" />My settings</button>
          <button role="menuitem" className="danger" onClick={() => { setOpen(false); setMe(null); nav('/crew') }}><Icon name="lock" />Lock my space</button>
        </div>
      )}
      <button className="me-chip" onClick={() => setOpen(o => !o)} aria-haspopup="menu" aria-expanded={open}>
        <Dot p={mine} size="sm" me />
        <span className="grow"><b className="who-name">{mine.name}</b><span className="small muted">Signed in</span></span>
        <Icon name="lock" />
      </button>
    </div>
  )
}
