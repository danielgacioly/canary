// The animated scenes of the opening story: a canary in a coal mine, the same canary flying out to the next frontier,
// and the data Canary is built on. Flat SVG and CSS only (no gradients, no glow); with reduced motion every scene is
// drawn at rest.
import type { Source } from '../api/types'
import './intro.css'

const reduced = () => {
  try {
    return document.documentElement.dataset.motion === 'reduce' || window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch { return false }
}

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

/** 1911: a mine gallery lit by a lamp, the canary breathing in its cage. */
export function MineScene() {
  return (
    <svg className="scene mine" viewBox="0 0 400 320" role="img" aria-label="A canary in a cage in a coal mine gallery, lit by a lamp">
      <rect width="400" height="320" rx="14" className="mine-air" />
      {/* rock above and below the gallery */}
      <path d="M0 0 H400 V74 L362 86 L318 70 L270 92 L222 76 L176 96 L128 78 L84 94 L40 80 L0 92 Z" className="rock" />
      <path d="M0 320 H400 V250 L356 240 L304 256 L250 238 L196 252 L142 236 L90 250 L44 238 L0 248 Z" className="rock" />
      {/* timber set: two posts and a cap */}
      <rect x="58" y="88" width="12" height="160" className="timber" />
      <rect x="318" y="84" width="12" height="166" className="timber" />
      <rect x="44" y="80" width="300" height="14" className="timber" />
      {/* rails */}
      <path d="M0 274 L400 266" className="rail" /><path d="M0 286 L400 278" className="rail" />
      {[30, 90, 150, 210, 270, 330, 390].map(x => <path key={x} d={`M${x - 8} 288 L${x + 4} 266`} className="sleeper" />)}
      {/* the lamp and the light it throws */}
      <path d="M262 112 L214 248 L356 248 L300 112 Z" className="lamp-light" />
      <rect x="276" y="94" width="2" height="12" className="wire" />
      <rect x="268" y="104" width="18" height="16" rx="3" className="lamp-body" />
      <circle cx="277" cy="114" r="5" className="lamp-flame" />
      {/* the cage hangs from the cap */}
      <rect x="179" y="94" width="2" height="24" className="wire" />
      <g className="cage">
        <path d="M136 176 C 136 120, 224 120, 224 176" className="cage-bar" />
        {[148, 162, 180, 198, 212].map(x => <path key={x} d={`M${x} ${x === 180 ? 122 : x === 162 || x === 198 ? 126 : 140} V214`} className="cage-bar" />)}
        <path d="M136 176 V214 M224 176 V214" className="cage-bar" />
        <path d="M142 190 H218" className="cage-bar thin" />
        <rect x="130" y="214" width="100" height="9" rx="2" className="cage-base" />
        <g transform="translate(152 168) scale(1.4)"><g className="breathe"><Bird /></g></g>
      </g>
      {/* dust drifting through the lamp light */}
      {[[236, 210, 0], [262, 176, 1.2], [300, 220, 2.1], [248, 150, 3.0], [322, 190, 0.6]].map(([x, y, d], k) =>
        <circle key={k} cx={x} cy={y} r="1.4" className="dust" style={{ animationDelay: `${d}s` }} />)}
    </svg>
  )
}

/** The next frontier: the cage door opens, the canary leaves the mine head and flies out toward the Moon and Mars. */
export function FlightScene() {
  const still = reduced()
  const path = 'M70 236 C 110 170, 150 196, 190 150 S 270 70, 336 82'
  return (
    <svg className="scene flight" viewBox="0 0 400 320" role="img" aria-label="The canary flies out of the mine toward the Moon and Mars">
      <rect width="400" height="320" rx="14" className="sky" />
      {/* the way out: orbit of Mars and the two destinations */}
      <path d="M-20 300 C 120 120, 300 40, 430 30" className="orbit" />
      <circle cx="98" cy="70" r="11" className="moon" />
      <circle cx="94" cy="66" r="2.2" className="crater" /><circle cx="103" cy="74" r="1.6" className="crater" />
      <circle cx="352" cy="44" r="15" className="mars" />
      <path d="M340 40 C 346 37, 356 38, 364 44" className="mars-line" />
      {/* Earth's ground and the mine head */}
      <path d="M0 262 C 120 252, 280 252, 400 262 V320 H0 Z" className="ground" />
      <g className="headframe">
        <path d="M44 262 L60 196 L76 262 M50 238 H70 M54 220 H66" className="frame" />
        <circle cx="60" cy="196" r="6" className="frame-wheel" />
      </g>
      {/* the open cage left on the ground */}
      <g transform="translate(92 236)">
        <path d="M0 22 C 0 2, 30 2, 30 22" className="cage-bar" />
        <path d="M6 22 V8 M15 22 V4 M24 22 V8" className="cage-bar" />
        <path d="M30 22 L42 12" className="cage-bar door" />
        <rect x="-3" y="22" width="36" height="5" rx="2" className="cage-base" />
      </g>
      {/* trail and bird */}
      <path d={path} className={`trail${still ? ' still' : ''}`} />
      {still ? (
        <g transform="translate(320 68)"><Bird flying /></g>
      ) : (
        <g>
          <g transform="translate(-18 -14)"><Bird flying /></g>
          <animateMotion dur="4.6s" begin="0.4s" fill="freeze" rotate="auto" keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines="0.4 0 0.2 1" path={path} />
        </g>
      )}
    </svg>
  )
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
