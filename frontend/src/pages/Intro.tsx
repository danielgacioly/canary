// Opening sequence: the canary story in four beats over the assembling body,
// then straight to the crew. Text rises out of a blur; each beat has its own timer.
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import BodyHologram from '../hologram/BodyHologram'
import { CanaryMark, Icon } from '../components/ui'

const BEATS = [
  { k: '1911 · Coal mines', h: 'For a century, miners carried a canary underground.', p: 'The bird felt bad air before people did. When it went quiet, the miners knew to leave, long before they felt anything themselves.' },
  { k: '2030s · Deep space', h: 'A spacecraft is a sealed mine.', p: 'Radiation, isolation, distance, altered gravity and a closed cabin. On the way to Mars, a question to the doctor takes up to 24 minutes to arrive, and as long to come back.' },
  { k: 'Canary · Crew health system', h: 'It notices before you do.', p: 'Canary compares every astronaut with their own normal, turns early warnings into goals, and guides the crew step by step when something goes wrong.' },
  { k: 'Built on NASA open data', h: 'Real storms. Real blood counts. Real distance.', p: 'NASA DONKI space weather, Curiosity radiation on Mars and Inspiration4 blood counts drive the story you are about to see.' },
]
const BEAT_MS = 6500

export default function Intro() {
  const [i, setI] = useState(0)
  const nav = useNavigate()
  const enter = () => {
    try { sessionStorage.setItem('canary.intro', '1') } catch { /* storage blocked */ }
    nav('/crew')
  }
  useEffect(() => {
    if (i >= BEATS.length - 1) return
    const t = setTimeout(() => setI(x => x + 1), BEAT_MS)
    return () => clearTimeout(t)
  }, [i])
  const status = useMemo(() => ({}), [])
  return (
    <div className="intro">
      <Stars />
      <div className="row reveal" style={{ padding: '24px 7vw 0' }}>
        <span className="brand"><CanaryMark size={26} />CANARY</span>
        <span className="small dim" style={{ marginLeft: 12 }}>NASA Space Apps Challenge 2026</span>
        <button className="btn sm ghost right" onClick={enter}>Skip intro<Icon name="chev" /></button>
      </div>
      <div className="intro-stage">
        <div className="intro-copy" key={i}>
          <span className="kicker reveal">{BEATS[i].k}</span>
          <h1 className="reveal d1">{BEATS[i].h}</h1>
          <p className="lead reveal d2">{BEATS[i].p}</p>
        </div>
        <div className="intro-holo reveal d1"><BodyHologram className="bodycard" status={status} interactive={false} autoRotate /></div>
      </div>
        <div className="intro-nav">
          {BEATS.map((_, k) => (
            <button key={k} className={`beatbar ${k < i ? 'done' : k === i ? 'on' : ''}`} onClick={() => setI(k)} aria-label={`Part ${k + 1}`}><i key={k === i ? `on${i}` : 'x'} /></button>
          ))}
          <button className="btn pri lg right" onClick={() => (i === BEATS.length - 1 ? enter() : setI(x => x + 1))}>{i === BEATS.length - 1 ? 'Enter Canary' : 'Next'}<Icon name="chev" /></button>
        </div>
    </div>
  )
}

function Stars() {
  const stars = useMemo(() => Array.from({ length: 160 }, () => ({ x: Math.random() * 100, y: Math.random() * 100, r: Math.random() * 1.4 + 0.3, d: 2.5 + Math.random() * 4, o: Math.random() * 3 })), [])
  return (
    <svg className="stars" aria-hidden="true">
      {stars.map((s, k) => (
        <circle key={k} cx={`${s.x}%`} cy={`${s.y}%`} r={s.r} fill="#dfe7f5">
          <animate attributeName="opacity" values=".1;.85;.1" dur={`${s.d}s`} begin={`${s.o}s`} repeatCount="indefinite" />
        </circle>
      ))}
    </svg>
  )
}
