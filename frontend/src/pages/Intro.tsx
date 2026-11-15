// Opening story, then the hand-off to the guided tour. Five chapters: the canary in the coal mine, the next frontier,
// what Canary is, the data it is built on, and how it works (it starts in Canary Control). The last chapter starts the
// tour (sessionStorage `canary.tour`), which continues in Canary Control and then on board.
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import BodyHologram from '../hologram/BodyHologram'
import Stars from '../components/Stars'
import { CanaryMark, Icon } from '../components/ui'
import { DataChapter, FlightScene, MineScene } from '../intro/Scenes'
import { useSession } from '../state/session'
import { startTour } from '../lib/tour'

const CHAPTERS = [
  { k: '1911, coal mines', h: 'For a century, miners carried a canary underground.',
    p: 'The bird felt bad air before people did. When it went quiet, the miners left in time, long before they felt anything themselves.' },
  { k: 'The next frontier', h: 'A century later, we look up.',
    p: 'To the next frontier: the Moon, Mars and the deep space between. Radiation, isolation, distance, altered gravity and a sealed cabin. We take the canary with us.' },
  { k: 'Canary', h: 'It notices before you do.',
    p: "Canary learns each astronaut's own normal, warns early, turns warnings into daily goals and guides the crew step by step in an emergency, even when Earth is twenty minutes away." },
  { k: 'The data', h: 'Built on NASA data.', p: '' },
  { k: 'How it works', h: 'It starts in Canary Control.', p: '' },
]
const LAST = CHAPTERS.length - 1
const AUTO = [7000, 7500, 7000, 0, 0]  // the data and the last chapter wait for the reader

export default function Intro() {
  const [i, setI] = useState(0)
  const nav = useNavigate()
  const { catalog, mission } = useSession()
  const registered = !!mission?.registered

  useEffect(() => {
    if (!AUTO[i]) return
    const t = setTimeout(() => setI(x => Math.min(LAST, x + 1)), AUTO[i])
    return () => clearTimeout(t)
  }, [i])

  const seen = () => { try { sessionStorage.setItem('canary.intro', '1') } catch { /* storage blocked */ } }
  const skip = () => { seen(); nav('/crew') }
  const start = () => { seen(); startTour(registered ? 'dashboard' : 'control'); nav('/control') }
  const ch = CHAPTERS[i]

  return (
    <div className="intro">
      <Stars />
      <div className="row intro-top">
        <span className="brand"><CanaryMark size={24} />CANARY</span>
        <button className="btn sm ghost right" onClick={skip}>Skip intro<Icon name="chev" /></button>
      </div>

      {i === 3 ? (
        <div className="intro-stage wide" key={i}>
          <div className="intro-copy">
            <h1 className="reveal">{ch.h}</h1>
            <p className="lead reveal d1">The baseline comes from NASA. The crew's blood is moulded on Inspiration4. The rest is simulated, and labelled as such.</p>
          </div>
          <DataChapter sources={catalog?.sources ?? []} />
        </div>
      ) : (
        <div className="intro-stage" key={i}>
          <div className="intro-copy">
            <h1 className="reveal">{ch.h}</h1>
            {i < LAST ? <p className="lead reveal d1">{ch.p}</p> : <HowItWorks registered={registered} onStart={start} />}
          </div>
          <div className="intro-visual">
            {i === 0 && <MineScene />}
            {i === 1 && <FlightScene />}
            {i >= 2 && <div className="intro-holo"><BodyHologram className="bodycard" status={{}} interactive={false} autoRotate /></div>}
          </div>
        </div>
      )}

      <div className="intro-nav">
        {CHAPTERS.map((c, k) => (
          <button key={k} className={`beat ${k < i ? 'done' : k === i ? 'on' : ''}`} onClick={() => setI(k)}>
            <span className="beatbar"><i key={k === i ? `on${i}` : 'x'} className={AUTO[k] ? '' : 'static'} style={AUTO[k] ? { animationDuration: `${AUTO[k]}ms` } : undefined} /></span>
            <span className="beat-l">{c.k}</span>
          </button>
        ))}
        {i < LAST && <button className="btn pri lg right" onClick={() => setI(x => x + 1)}>Next<Icon name="chev" /></button>}
      </div>
    </div>
  )
}

/** The steps ahead, and the door into Canary Control. */
function HowItWorks({ registered, onStart }: { registered: boolean; onStart: () => void }) {
  const steps = [
    ['Canary Control', 'Mission Control registers the mission, the crew and their accounts, and connects each astronaut\'s devices.'],
    ['On Earth', 'The flight surgeon and Mission Control follow operational status and messages, with the real signal delay. Health details stay on board.'],
    ['On board', 'Each astronaut sees their own body, goals and alerts. The crew medical officer sees everyone, and Guided Response is one hold away.'],
  ]
  return (
    <>
      <ol className="steps-ahead">
        {steps.map(([t, d], k) => (
          <li key={t} style={{ animationDelay: `${250 + k * 140}ms` }}><span className="n">{k + 1}</span><span><b>{t}</b><span className="small muted">{d}</span></span></li>
        ))}
      </ol>
      <div className="reveal d2">
        <button className="btn pri lg pulse" onClick={onStart}>{registered ? 'Open Canary Control' : 'Start in Canary Control'}<Icon name="chev" /></button>
      </div>
    </>
  )
}
