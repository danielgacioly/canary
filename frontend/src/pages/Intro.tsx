// Opening sequence: the canary story in four beats over the assembling body, then the mission
// as the mission admin configured it (itinerary and crew come from that future admin flow).
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { Plan } from '../api/types'
import BodyHologram from '../hologram/BodyHologram'
import Stars from '../components/Stars'
import Timeline from '../components/Timeline'
import { CanaryMark, Icon } from '../components/ui'
import { useSession } from '../state/session'

const BEATS = [
  { k: '1911, coal mines', h: 'For a century, miners carried a canary underground.', p: 'The bird felt bad air before people did. When it went quiet, the miners knew to leave, long before they felt anything themselves.' },
  { k: '2030s, deep space', h: 'A spacecraft is a sealed mine.', p: 'Radiation, isolation, distance, altered gravity and a closed cabin. On the way to Mars, a question to the doctor takes up to 24 minutes to arrive, and as long to come back.' },
  { k: 'Canary', h: 'It notices before you do.', p: 'Canary compares every astronaut with their own normal, turns early warnings into goals, and guides the crew step by step when something goes wrong.' },
  { k: 'NASA open data', h: 'Real storms. Real blood counts. Real distance.', p: 'NASA DONKI space weather, Curiosity radiation on Mars and Inspiration4 blood counts drive the story you are about to see.' },
]
const LAST = BEATS.length  // index of the "mission ready" beat
const BEAT_MS = 6500

export default function Intro() {
  const [i, setI] = useState(0)
  const nav = useNavigate()
  const { catalog } = useSession()
  const [plan, setPlan] = useState<Plan | null>(null)
  useEffect(() => { api.plan().then(setPlan).catch(() => undefined) }, [])
  const enter = () => {
    try { sessionStorage.setItem('canary.intro', '1') } catch { /* storage blocked */ }
    nav('/crew')
  }
  useEffect(() => {
    if (i >= LAST) return
    const t = setTimeout(() => setI(x => x + 1), BEAT_MS)
    return () => clearTimeout(t)
  }, [i])
  const status = useMemo(() => ({}), [])
  const ready = i === LAST

  return (
    <div className="intro">
      <Stars />
      <div className="row intro-top">
        <span className="brand"><CanaryMark size={24} />CANARY</span>
        <span className="small dim">NASA Space Apps Challenge 2026</span>
        <button className="btn sm ghost right" onClick={enter}>Skip intro<Icon name="chev" /></button>
      </div>
      <div className="intro-stage">
        {!ready ? (
          <div className="intro-copy" key={i}>
            <h1 className="reveal">{BEATS[i].h}</h1>
            <p className="lead reveal d1">{BEATS[i].p}</p>
          </div>
        ) : (
          <MissionReady plan={plan} crew={catalog?.crew ?? []} places={catalog?.locations} />
        )}
        <div className="intro-holo reveal"><BodyHologram className="bodycard" status={status} interactive={false} autoRotate /></div>
      </div>
      <div className="intro-nav">
        {[...BEATS.map(b => b.k), 'Your mission'].map((label, k) => (
          <button key={k} className={`beat ${k < i ? 'done' : k === i ? 'on' : ''}`} onClick={() => setI(k)}>
            <span className="beatbar"><i key={k === i ? `on${i}` : 'x'} className={k === LAST ? 'static' : ''} /></span>
            <span className="beat-l">{label}</span>
          </button>
        ))}
        <button className="btn pri lg right" onClick={() => (ready ? enter() : setI(x => x + 1))}>{ready ? 'Enter Canary' : 'Next'}<Icon name="chev" /></button>
      </div>
    </div>
  )
}

/** The last beat: the mission as configured, drawn in. Nothing to fill in here. */
function MissionReady({ plan, crew, places }: { plan: Plan | null; crew: { id: string; name: string; initials: string; role: string }[]; places?: Record<string, { name: string; reply: string; gravity: string }> }) {
  if (!plan || !places) return <div className="intro-copy" />
  const flight = plan.legs[plan.legs.length - 1].end + 1
  const dest = [...plan.legs].reverse().find(l => l.location !== 'earth' && l.location !== 'rocket') ?? plan.legs[plan.legs.length - 1]
  const where = places[dest.location]
  return (
    <div className="intro-copy ready" key="ready">
      <h1 className="reveal">{plan.name}. Four crew, {flight} days.</h1>
      <p className="lead reveal d1">Itinerary and crew are set by mission control. Destination: {where.name}, {where.gravity} gravity, Earth replies in {where.reply.toLowerCase()}. Canary adapts to every leg on its own.</p>
      <div className="reveal d2"><Timeline legs={plan.legs} places={places} now={0} nowLabel="Launch" compact /></div>
      <div className="ready-crew">
        {crew.map((c, k) => (
          <div key={c.id} className="reveal" style={{ animationDelay: `${700 + k * 90}ms` }}>
            <span className="pdot md neutral"><span className="ini">{c.initials}</span></span>
            <span><b>{c.name}</b><span className="small muted">{c.role}</span></span>
          </div>
        ))}
      </div>
    </div>
  )
}
