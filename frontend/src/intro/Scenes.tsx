// The animated scenes of the opening story: a canary in a coal mine, the same canary flying out to the next frontier,
// and the data Canary is built on. Flat SVG and CSS only (no gradients, no glow); with reduced motion every scene is
// drawn at rest.
import type { Source } from '../api/types'
import './intro.css'

/** A canary seen from the side, facing right, about 40 × 26 units. The wing flaps when `flying`. */
export function Bird({ flying = false }: { flying?: boolean }) {
  return (
    <g className={`bird${flying ? ' flying' : ''}`}>
      <path d="M1 15 L10 12.5 L10 18.5 Z" className="bird-tail" />
      <ellipse cx="18" cy="15.5" rx="9.5" ry="6.6" className="bird-body" />
      <circle cx="27.2" cy="10.6" r="5.2" className="bird-body" />
      <path d="M31.8 9.4 L37 11 L31.8 12.6 Z" className="bird-beak" />
      <circle cx="28.8" cy="9.6" r="1.05" className="bird-eye" />
      <path d="M12.5 14 C 14.5 5.5, 21.5 4.8, 23.5 13.2 Z" className="bird-wing" />
    </g>
  )
}

/** 1911: a miner and his canary (photograph). */
export function MineScene() {
  return <img className="scene photo" src="/intro/miner-canary.png" alt="A miner with a helmet lamp holds up a canary in a small cage" />
}

/** The next frontier: the night sky over the Earth (photograph). */
export function FlightScene() {
  return <img className="scene photo" src="/intro/night-sky.webp" alt="The Milky Way over a dark forest and a still lake" />
}

const BASELINE = ['nasa:donki', 'nasa:rad', 'nasa:std3001v1', 'nasa:hrp']
const MOULD = ['nasa:osd569', 'nasa:osd575']

/** Where the numbers come from: NASA for the baseline, Inspiration4 as the mould of the crew, the rest simulated. */
export function DataChapter({ sources }: { sources: Source[] }) {
  const pick = (ids: string[]) => ids.map(id => sources.find(s => s.id === id)).filter((s): s is Source => !!s)
  return (
    <div className="data-cols">
      <section className="data-col" style={{ ['--k' as string]: 0 }}>
        <h3>NASA, the baseline</h3>
        <p className="small muted">Space weather, radiation on Mars, the limits astronauts are held to and the hazards of spaceflight.</p>
        <ul>{pick(BASELINE).map(s => <li key={s.id}><a href={s.url} target="_blank" rel="noreferrer">{s.name}</a><span className="small dim">{s.org}</span></li>)}</ul>
      </section>
      <section className="data-col" style={{ ['--k' as string]: 1 }}>
        <h3>Inspiration4, the mould</h3>
        <p className="small muted">SpaceX's 2021 all-civilian orbital flight. Its crew's blood before, during and after flight, published by NASA, shapes the blood of our crew.</p>
        <ul>{pick(MOULD).map(s => <li key={s.id}><a href={s.url} target="_blank" rel="noreferrer">{s.name}</a><span className="small dim">{s.org}</span></li>)}</ul>
      </section>
      <section className="data-col" style={{ ['--k' as string]: 2 }}>
        <h3>Simulated, and said so</h3>
        <p className="small muted">Daily vitals, sleep, self-tests and the mission story are simulated on those patterns. Every reading carries its origin, so a simulated value is never shown as a real one.</p>
      </section>
    </div>
  )
}
