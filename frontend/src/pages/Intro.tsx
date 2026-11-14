// Opening sequence: the canary story in four beats over the hologram, then "who is at this terminal?".
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import BodyHologram from '../hologram/BodyHologram'
import { Avatar, CanaryMark, Icon } from '../components/ui'
import { useSession } from '../state/session'

const BEATS = [
  { k: '1922 · Coal mines', h: <>For a century, miners carried a <em>canary</em> underground.</>,
    p: 'The bird is small and feels bad air before people do. When it went quiet, the miners knew to leave, long before they felt anything themselves.' },
  { k: '2030s · Deep space', h: <>A spacecraft is a <em>sealed mine</em>.</>,
    p: 'Radiation, isolation, distance, altered gravity and a closed cabin. On the way to Mars, a question to the doctor takes up to 24 minutes to arrive, and as long to come back.' },
  { k: 'Canary · Crew health system', h: <>It notices <em>before you do</em>.</>,
    p: 'Canary compares every astronaut with their own normal, turns early warnings into goals, and guides the crew step by step when something goes wrong. Physical and mental, side by side.' },
  { k: 'Built on NASA open data', h: <>Real storms. Real blood counts. <em>Real distance.</em></>,
    p: 'NASA DONKI space weather, Curiosity RAD dose on Mars and Inspiration4 blood counts drive the story you are about to see.' },
]

export default function Intro() {
  const { catalog, setMe, mission } = useSession()
  const [params] = useSearchParams()
  const [i, setI] = useState(params.get('pick') ? BEATS.length : 0)
  const nav = useNavigate()
  useEffect(() => {
    if (i >= BEATS.length) return
    const t = setTimeout(() => setI(x => x + 1), 7000)
    return () => clearTimeout(t)
  }, [i])
  const picking = i >= BEATS.length
  const beat = BEATS[Math.min(i, BEATS.length - 1)]
  const status = useMemo(() => ({}), [])
  return (
    <div className="intro">
      <Stars />
      <div className="row" style={{ position: 'relative', zIndex: 2, padding: '24px 7vw 0' }}>
        <CanaryMark size={30} /><b style={{ font: '800 18px var(--f-display)', fontStretch: '125%', letterSpacing: '.2em' }}>CANARY</b>
        <span className="lbl" style={{ marginLeft: 10 }}>NASA Space Apps Challenge 2026</span>
        {!picking && <button className="btn sm ghost right" onClick={() => setI(BEATS.length)}>Skip intro<Icon name="chev" size={14} /></button>}
      </div>
      <div className="intro-stage">
        {!picking ? (
          <div className="intro-copy" key={i}>
            <span className="lbl reveal" style={{ color: 'var(--gold)' }}>{beat.k}</span>
            <h1 className="reveal d1 hello"><span>{beat.h}</span></h1>
            <p className="lead reveal d2">{beat.p}</p>
          </div>
        ) : (
          <div className="intro-copy" style={{ maxWidth: 760 }}>
            <span className="lbl reveal" style={{ color: 'var(--gold)' }}>No accounts on board</span>
            <h1 className="reveal d1">Who is at this terminal?</h1>
            <p className="lead reveal d2">Tap your name. Only the medical team signs in.{mission ? ` The demo story suggests ${catalog?.crew.find(c => c.id === mission.suggested_user)?.name.split(' ')[0]} for this step.` : ''}</p>
            <div className="pick reveal d3">
              {catalog?.crew.map(c => (
                <button key={c.id} onClick={() => { setMe(c.id); nav('/me') }} style={mission?.suggested_user === c.id ? { borderColor: 'var(--cyan)' } : undefined}>
                  <Avatar initials={c.initials} size="lg" />
                  <div><b style={{ fontSize: 15 }}>{c.name}</b><div className="lbl" style={{ marginTop: 4 }}>{c.role}</div><div className="small dim" style={{ marginTop: 4 }}>{c.home}</div></div>
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="intro-holo"><BodyHologram className="holo-wrap" status={status} interactive={false} autoRotate /></div>
      </div>
      <div className="intro-nav">
        {BEATS.map((_, k) => <button key={k} onClick={() => setI(k)} aria-label={`Part ${k + 1}`} style={{ width: 34, height: 3, borderRadius: 3, background: k === i ? 'var(--cyan)' : k < i ? 'rgba(94,242,255,.4)' : 'var(--line-2)' }} />)}
        {!picking && <button className="btn pri right" onClick={() => setI(x => x + 1)}>{i === BEATS.length - 1 ? 'Enter Canary' : 'Next'}<Icon name="chev" size={14} /></button>}
      </div>
    </div>
  )
}

function Stars() {
  const stars = useMemo(() => Array.from({ length: 140 }, () => ({ x: Math.random() * 100, y: Math.random() * 100, s: Math.random() * 1.6 + 0.3, d: Math.random() * 4 })), [])
  return (
    <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }} aria-hidden="true">
      {stars.map((s, k) => <circle key={k} cx={`${s.x}%`} cy={`${s.y}%`} r={s.s} fill="#cfe9ff" opacity=".6"><animate attributeName="opacity" values=".15;.8;.15" dur={`${3 + s.d}s`} repeatCount="indefinite" /></circle>)}
    </svg>
  )
}
