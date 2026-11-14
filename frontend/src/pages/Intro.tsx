// Opening: the canary story in three short beats over the body, then "who is at this terminal?".
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import BodyHologram from '../hologram/BodyHologram'
import { Avatar, CanaryMark, Icon } from '../components/ui'
import { useSession } from '../state/session'

const BEATS = [
  { h: 'For a century, miners carried a canary underground.', p: 'The bird felt bad air before people did. When it went quiet, the miners knew to leave.' },
  { h: 'A spacecraft is a sealed mine.', p: 'Radiation, isolation, altered gravity, a closed cabin. On the way to Mars, a question to the doctor takes up to 24 minutes to arrive.' },
  { h: 'Canary notices before you do.', p: 'It compares you with your own normal, turns early warnings into goals, and guides the crew step by step when something goes wrong.' },
]

export default function Intro() {
  const { catalog, setMe, mission } = useSession()
  const [params] = useSearchParams()
  const [i, setI] = useState(params.get('pick') ? BEATS.length : 0)
  const nav = useNavigate()
  useEffect(() => {
    if (i >= BEATS.length) return
    const t = setTimeout(() => setI(x => x + 1), 6500)
    return () => clearTimeout(t)
  }, [i])
  const picking = i >= BEATS.length
  const status = useMemo(() => ({}), [])
  return (
    <div className="intro">
      <div className="row" style={{ padding: '22px 7vw 0' }}>
        <span className="brand"><CanaryMark />CANARY</span>
        {!picking && <button className="btn sm ghost right" onClick={() => setI(BEATS.length)}>Skip</button>}
      </div>
      <div className="intro-stage">
        {!picking ? (
          <div className="intro-copy" key={i}>
            <h1 className="reveal">{BEATS[i].h}</h1>
            <p className="lead reveal d1">{BEATS[i].p}</p>
          </div>
        ) : (
          <div className="intro-copy">
            <h1 className="reveal">Who is at this terminal?</h1>
            <p className="lead reveal d1">Tap your name. There are no accounts on board; only the medical team signs in.</p>
            <div className="pick reveal d2">
              {catalog?.crew.map(c => (
                <button key={c.id} onClick={() => { setMe(c.id); nav('/today') }} style={mission?.suggested_user === c.id ? { boxShadow: 'inset 0 0 0 1px var(--ink)' } : undefined}>
                  <Avatar initials={c.initials} size="lg" />
                  <div><b>{c.name}</b><div className="small muted">{c.role}</div></div>
                </button>
              ))}
            </div>
            {mission && <p className="small dim">The demo story suggests {catalog?.crew.find(c => c.id === mission.suggested_user)?.name} for this step.</p>}
          </div>
        )}
        <div className="intro-holo"><BodyHologram className="bodycard" status={status} interactive={false} autoRotate /></div>
      </div>
      {!picking && (
        <div className="intro-nav">
          {BEATS.map((_, k) => <button key={k} onClick={() => setI(k)} aria-label={`Part ${k + 1}`} style={{ width: 28, height: 3, borderRadius: 3, background: k === i ? 'var(--ink)' : 'var(--line-2)' }} />)}
          <button className="btn pri right" onClick={() => setI(x => x + 1)}>{i === BEATS.length - 1 ? 'Start' : 'Next'}<Icon name="chev" /></button>
        </div>
      )}
    </div>
  )
}
