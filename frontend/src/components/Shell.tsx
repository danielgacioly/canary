import { useRef, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import AskCanary from '../features/AskCanary'
import GuidedResponse from '../features/GuidedResponse'
import { useApi, useSession } from '../state/session'
import { CrewDots, Dot } from './People'
import { CanaryMark, Icon } from './ui'

// Crew first: the system always opens on the whole crew. Personal data sits behind "Your space".
const NAV: { group: string; items: [string, string, string][] }[] = [
  { group: 'Crew', items: [['/crew', 'crew', 'Crew'], ['/plan', 'plan', 'Mission plan'], ['/ranking', 'rank', 'Ranking']] },
  { group: 'Your space', items: [['/today', 'today', 'My health'], ['/goals', 'goals', 'My goals']] },
]

export default function Shell() {
  const { mission, me, setMe, emergency, setEmergency, askOpen, setAskOpen, toasts } = useSession()
  const [where, setWhere] = useState(false)
  const nav = useNavigate()
  const { data: crew } = useApi(() => api.overview(), [])
  const mine = crew?.people.find(c => c.id === me)
  // First run (and after a demo reset): the mission is set up before anything else.

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
                {(to === '/today' || to === '/goals') && !me && <span className="count" style={{ color: 'var(--dim)' }}><Icon name="lock" size={13} /></span>}
              </NavLink>
            ))}
          </div>
        ))}
        <div className="group">Support</div>
        <button className="nav" onClick={() => setAskOpen(true)}><Icon name="ask" /><span>Ask Canary</span></button>
        <NavLink to="/medical" className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}><Icon name="med" /><span>Medical console</span></NavLink>
        <NavLink to="/about" className={({ isActive }) => `nav ${isActive ? 'active' : ''}`}><Icon name="info" /><span>About & data</span></NavLink>
        <ThemeToggle />
        <div className="foot">
          {mine ? (
            <button className="me-chip" onClick={() => { setMe(null); nav('/crew') }} title="Lock your space">
              <Dot p={mine} size="sm" me />
              <span className="grow"><b style={{ display: 'block', fontSize: 14 }}>{mine.name}</b><span className="small muted">Lock my space</span></span>
              <Icon name="lock" />
            </button>
          ) : (
            <button className="me-chip" onClick={() => nav('/today')} title="Enter your private space">
              <span className="pdot sm"><Icon name="lock" /></span>
              <span className="grow"><b style={{ display: 'block', fontSize: 14 }}>Enter my space</b><span className="small muted">Your health is private</span></span>
            </button>
          )}
        </div>
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
          <div className="right row" style={{ gap: 18 }}>{crew && <CrewDots people={crew.people} />}<HoldButton onFire={() => setEmergency(true)} /></div>
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
  const [busy, setBusy] = useState(false)
  if (!mission || !catalog) return null
  const go = async (i: number) => { setBusy(true); try { await setStep(i) } finally { setBusy(false) } }
  return (
    <div className="story">
      <span className="small" style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>Demo {mission.step + 1}/{mission.steps}</span>
      <div className="dots">{catalog.story.map((_, i) => <button key={i} className={i === mission.step && !mission.custom_day ? 'on' : ''} onClick={() => go(i)} aria-label={`Story step ${i + 1}`} disabled={busy} />)}</div>
      <p className="grow">{mission.custom_day ? <><b style={{ color: 'var(--ink)' }}>Free navigation.</b> You picked day {mission.day} on the mission plan. Press a dot to return to the story.</> : <><b style={{ color: 'var(--ink)' }}>{mission.story.when}.</b> {mission.story.text}</>}</p>
      {!mission.custom_day && me !== mission.suggested_user && (
        <button className="btn sm ghost" onClick={() => nav(`/today?who=${mission.suggested_user}`)} title="Opens the PIN pad for this person">
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
  if (!mission) return null
  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal wide" onClick={e => e.stopPropagation()}>
        <div className="row"><h2>Where are you?</h2><button className="btn sm ghost right" onClick={onClose} aria-label="Close"><Icon name="close" /></button></div>
        <p className="muted" style={{ margin: '6px 0 18px' }}>
          The mission plan puts you at <b style={{ color: 'var(--ink)' }}>{mission.leg.label || mission.leg.location}</b> today. Pick another place to simulate it, or <button className="link" onClick={() => { onClose(); nav('/plan') }}>edit the mission plan</button>.
        </p>
        <PlaceGrid current={mission.location} onPick={async (k, name) => { await setLocation(k); toast(`Simulating: ${name}`); onClose() }} />
        {mission.location_override && <button className="btn" style={{ marginTop: 16 }} onClick={async () => { await setLocation(null); onClose() }}>Back to the mission plan</button>}
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

/** Dark is the default on board; light for bright rooms. Remembered on this device. */
function ThemeToggle() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme === 'light' ? 'light' : 'dark')
  const flip = () => {
    const next = theme === 'light' ? 'dark' : 'light'
    document.documentElement.dataset.theme = next
    try { localStorage.setItem('canary.theme', next) } catch { /* storage blocked */ }
    setTheme(next)
  }
  return (
    <button className="nav theme-toggle" onClick={flip} aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}>
      <Icon name={theme === 'light' ? 'moon' : 'sun'} /><span>{theme === 'light' ? 'Dark mode' : 'Light mode'}</span>
    </button>
  )
}
