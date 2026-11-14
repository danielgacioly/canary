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
  const [menu, setMenu] = useState(false)
  const nav = useNavigate()
  const { data: crew } = useApi(() => api.crew(), [])
  const meInfo = catalog?.crew.find(c => c.id === me)
  const mine = crew?.crew.find(c => c.id === me)

  useEffect(() => { if (!me) nav('/welcome') }, [me, nav])

  return (
    <>
      <header className="bar">
        <NavLink to="/today" className="brand"><CanaryMark />CANARY</NavLink>
        <nav className="tabsnav" aria-label="Main">
          <NavLink to="/today">Today{mine && mine.level > 0 && <span className={`count s${mine.level}`}>●</span>}</NavLink>
          <NavLink to="/goals">Goals</NavLink>
          <NavLink to="/crew">Crew</NavLink>
          <NavLink to="/mission">Mission</NavLink>
        </nav>
        <div className="row right" style={{ gap: 6 }}>
          {mission && (
            <button className="place-btn opt" onClick={() => setWhere(true)} title="Change where you are">
              <b>{mission.place.name} · {mission.day_label}</b>
              <span>{mission.place.gravity} · Earth replies {mission.place.reply === 'Live' ? 'live' : `in ${mission.place.reply}`}</span>
            </button>
          )}
          <div style={{ position: 'relative' }}>
            <button onClick={() => setMenu(m => !m)} aria-label="Menu" title={meInfo?.name}>{meInfo && <Avatar initials={meInfo.initials} />}</button>
            {menu && (
              <div className="card pad-sm" style={{ position: 'absolute', right: 0, top: 46, width: 240, zIndex: 40, boxShadow: '0 20px 50px rgba(0,0,0,.5)' }} onMouseLeave={() => setMenu(false)}>
                <div style={{ padding: '4px 4px 10px' }}><b>{meInfo?.name}</b><div className="small muted">{meInfo?.role} · this terminal</div></div>
                <div className="list">
                  <button className="item" onClick={() => { setMenu(false); setMe(null); nav('/welcome?pick=1') }}>Switch crew member</button>
                  <button className="item" onClick={() => { setMenu(false); setAskOpen(true) }}>Ask Canary</button>
                  <button className="item" onClick={() => { setMenu(false); nav('/medical') }}>Medical console</button>
                  <button className="item" onClick={() => { setMenu(false); nav('/about') }}>About & data</button>
                </div>
              </div>
            )}
          </div>
          <HoldButton onFire={() => setEmergency(true)} />
        </div>
      </header>
      <Outlet />
      <StoryBar />
      {where && <WherePicker onClose={() => setWhere(false)} />}
      {emergency && <GuidedResponse onClose={() => setEmergency(false)} />}
      {askOpen && <AskCanary onClose={() => setAskOpen(false)} />}
      <div className="toasts">{toasts.map(t => <div key={t.id} className="toast">{t.t}</div>)}</div>
    </>
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
  const { mission, setStep, catalog } = useSession()
  const [busy, setBusy] = useState(false)
  if (!mission || !catalog) return null
  const go = async (i: number) => { setBusy(true); try { await setStep(i) } finally { setBusy(false) } }
  return (
    <div className="story">
      <span className="small" style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>Demo {mission.step + 1}/{mission.steps}</span>
      <div className="dots">{catalog.story.map((_, i) => <button key={i} className={i === mission.step ? 'on' : ''} onClick={() => go(i)} aria-label={`Story step ${i + 1}`} disabled={busy} />)}</div>
      <p className="grow"><b style={{ color: 'var(--ink)' }}>{mission.story.when}.</b> {mission.story.text}</p>
      <button className="btn sm ghost" disabled={busy || mission.step === 0} onClick={() => go(mission.step - 1)} aria-label="Previous step"><Icon name="back" /></button>
      <button className="btn sm" disabled={busy || mission.step === mission.steps - 1} onClick={() => go(mission.step + 1)}>Next<Icon name="chev" /></button>
    </div>
  )
}

function WherePicker({ onClose }: { onClose: () => void }) {
  const { catalog, mission, setLocation, toast } = useSession()
  if (!catalog || !mission) return null
  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal wide" onClick={e => e.stopPropagation()}>
        <div className="row"><h2>Where are you?</h2><button className="btn sm ghost right" onClick={onClose} aria-label="Close"><Icon name="close" /></button></div>
        <p className="muted" style={{ margin: '6px 0 18px' }}>The place changes your goals, your alerts and every emergency step.</p>
        <PlaceGrid onPick={async (k, name) => { await setLocation(k); toast(`Now at: ${name}`); onClose() }} current={mission.location} />
      </div>
    </div>
  )
}

export function PlaceGrid({ onPick, current }: { onPick: (k: string, name: string) => void; current: string }) {
  const { catalog } = useSession()
  if (!catalog) return null
  return (
    <div className="places">
      {Object.entries(catalog.locations).map(([k, p]) => (
        <button key={k} className={`place ${current === k ? 'on' : ''}`} onClick={() => onPick(k, p.name)}>
          <div><h3>{p.name}</h3><span className="small muted">{p.sub}</span></div>
          <dl><dt>Gravity</dt><dd>{p.gravity}</dd><dt>Earth replies</dt><dd>{p.reply}</dd><dt>Hospital</dt><dd>{p.hospital}</dd><dt>Radiation</dt><dd>{p.dose_rate} mSv/day</dd></dl>
          <span className="small muted">{p.what}</span>
        </button>
      ))}
    </div>
  )
}
