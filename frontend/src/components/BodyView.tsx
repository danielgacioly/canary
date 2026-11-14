// Health: the body and the verdict first, then the numbers of the current lens as tiles:
// Physical shows the physical systems, Mental the mental facets (charts live on the Dashboard tab). Click any part of the body or any tile and the
// verdict area becomes that system.
import { useMemo, useRef, useState, type CSSProperties } from 'react'
import type { CrewDetail, GuideEntry, HazardId, Indicator, Risk } from '../api/types'
import type { CheckKind } from '../features/Checks'
import type { SystemId } from '../hologram/anatomy'
import BodyHologram from '../hologram/BodyHologram'
import type { Lens } from '../hologram/scene'
import { amslerResult, attention, bonePctOfPreflight, nasaRaises } from '../lib/health'
import { useSession } from '../state/session'
import EvaReadiness from './EvaReadiness'
import RadiationBar from './RadiationBar'
import { CountUp, Icon, Status } from './ui'

const fmt = (i: Indicator) => i.value.toFixed(i.dp)
const PHYSICAL: SystemId[] = ['heart', 'lungs', 'skeleton', 'muscles', 'eyes', 'kidneys', 'gut', 'immune', 'skin']
const FACETS = ['sleep', 'react', 'mood', 'stress', 'social']
const HAZARD_NAME: Record<HazardId, string> = { R: 'Radiation', I: 'Isolation', D: 'Distance', G: 'Gravity', E: 'Environment' }
const TREND = { rising: 'Rising', stable: 'Stable', falling: 'Falling' } as const
const DATA = { real: 'Measured data', partial: 'Part measured, part simulated', simulated: 'Simulated data' } as const

/** Letters of the RIDGE hazards that may be factors; a possible factor, never a cause. */
function Letters({ ids }: { ids: HazardId[] }) {
  if (!ids.length) return null
  return <span className="letters" title={`Possible factors: ${ids.map(h => HAZARD_NAME[h]).join(', ')}`}>{ids.map(h => <i key={h}>{h}</i>)}</span>
}

export default function BodyView({ d, onCheck, self = true }: { d: CrewDetail; onCheck?: (k: CheckKind) => void; self?: boolean }) {
  const [lens, setLens] = useState<Lens>(d.areas.mental.level > d.areas.physical.level ? 'mental' : 'physical')
  const [sel, setSel] = useState<SystemId | null>(null)
  const status = useMemo(() => Object.fromEntries(Object.entries(d.systems).map(([k, v]) => [k, v.level])) as Record<SystemId, 0 | 1 | 2>, [d.systems])
  const names = useMemo(() => Object.fromEntries(Object.entries(d.systems).map(([k, v]) => [k, v.name])), [d.systems])
  const hero = useRef<HTMLElement>(null)
  const apply = (s: SystemId | null) => {
    setSel(s)
    if (s) setLens(d.systems[s]?.area === 'mental' ? 'mental' : 'physical')
  }
  // From a tile below the fold: bring the body into view first, then change it, so the
  // camera and lens transition play where you can see them instead of off screen.
  const choose = (s: SystemId | null, scroll = false) => {
    const top = hero.current?.getBoundingClientRect().top ?? 0
    if (!scroll || top > -40) { apply(s); return }
    window.scrollBy({ top: top - 80, behavior: 'smooth' })
    let done = false
    const go = () => { if (done) return; done = true; window.removeEventListener('scrollend', go); apply(s) }
    window.addEventListener('scrollend', go)
    window.setTimeout(go, 700)
  }
  const physical = [...PHYSICAL].sort((a, b) => d.systems[b].level - d.systems[a].level)
  const mental = [...FACETS].sort((a, b) => d.indicators[b].level - d.indicators[a].level)

  return (
    <>
      <section className="hero" ref={hero}>
        <div className="rise">
          <BodyHologram status={status} lens={lens} selected={sel} onSelect={s => choose(s)} names={names}>
            <span className="body-hint">Drag to turn · click any part of the body</span>
          </BodyHologram>
        </div>
        <div className="hero-side">
          {sel ? <SystemPanel key={sel} d={d} sys={sel} onBack={() => choose(null)} onCheck={self ? onCheck : undefined} />
            : <Verdict d={d} self={self} onCheck={onCheck} onPick={s => choose(s)} />}
          <div className="areas rise" style={{ ['--d' as string]: 4 }}>
            {(['physical', 'mental'] as const).map(a => (
              <button key={a} className={`area ${lens === a ? 'on' : ''}`} onClick={() => { setLens(a); setSel(null) }} aria-pressed={lens === a}>
                <div className="k">{a === 'physical' ? 'Physical' : 'Mental'}</div>
                <b className="num"><CountUp value={d.areas[a].score} /></b>
                <Status level={d.areas[a].level} />
              </button>
            ))}
          </div>
        </div>
      </section>

      {lens === 'physical' ? (
        <section id="sec-physical" key="physical">
          <div className="section-head rise"><h2>Physical</h2><span className="sub">{d.areas.physical.score} · sorted by what needs attention</span></div>
          <Tiles count={physical.length}>
            {physical.map((s, i) => <PhysicalTile key={s} d={d} s={s} i={i} on={sel === s} onPick={() => choose(s, true)} />)}
          </Tiles>
        </section>
      ) : (
        <section id="sec-mental" key="mental">
          <div className="section-head rise"><h2>Mental</h2><span className="sub">{d.areas.mental.score} · rest, focus, mood, stress, connection</span></div>
          <Tiles count={mental.length}>
            {mental.map((k, i) => {
              const ind = d.indicators[k]
              return (
                <button key={k} className={`tile rise s${ind.level} ${sel === 'brain' ? 'on' : ''}`} style={{ ['--d' as string]: i }} onClick={() => choose('brain', true)}>
                  <div className="top"><span className="dot" />{ind.facet}<span className="small dim right">{ind.name}</span></div>
                  <Reading ind={ind} />
                </button>
              )
            })}
          </Tiles>
        </section>
      )}
    </>
  )
}

/** Columns that divide the tiles evenly (nine physical tiles make three by three); whatever is left over, the last tile stretches over. */
function Tiles({ count, children }: { count: number; children: React.ReactNode }) {
  const cols = [4, 5, 3].find(k => count % k === 0) ?? 4
  const rest = count % cols
  return <div className="tiles" style={{ ['--cols' as string]: cols, ['--last-span' as string]: rest ? cols - rest + 1 : 1 } as CSSProperties}>{children}</div>
}

/** The number of one indicator, with the population range only when the value is outside it. */
function Reading({ ind }: { ind: Indicator }) {
  const p = ind.population
  return (
    <div className="tile-body">
      <div className="tv">{fmt(ind)}<small>{ind.unit}</small></div>
      <div className="small dim">normal {ind.baseline.toFixed(ind.dp)}</div>
      {p.status !== 'in' && p.low !== null && p.high !== null && <div className="small tile-out">usual range {p.low}–{p.high}</div>}
    </div>
  )
}

function PhysicalTile({ d, s, i, on, onPick }: { d: CrewDetail; s: SystemId; i: number; on: boolean; onPick: () => void }) {
  const st = d.systems[s]
  const ind = st.indicators[0] ? d.indicators[st.indicators[0]] : null
  const nasa = nasaRaises(d, st.indicators)
  let body
  if (s === 'skeleton' && ind && d.indicators.bone) {
    const bone = d.indicators.bone
    body = <div className="tile-body"><div className="tv">{bonePctOfPreflight(bone).toFixed(1)}<small>% of pre-flight</small></div><div className="small dim">estimated from days in flight</div></div>
  } else if (s === 'eyes') {
    const a = amslerResult(d)
    body = <div className="tile-body"><div className="tv">{a.label}</div><div className="small dim">{a.day === null ? 'Amsler grid, not done yet' : `Amsler grid, day ${a.day}`}</div></div>
  } else if (s === 'skin') {
    const x = d.dose
    body = (
      <div className="tile-body">
        <div className="tv">{x.career_msv ?? x.mission_msv}<small>mSv {x.career_msv === undefined ? 'this mission' : 'career'}</small></div>
        {x.career_msv !== undefined ? <RadiationBar d={d} compact /> : null}
        <div className="small dim">{x.career_pct_of_limit ?? x.pct_of_limit}% of NASA's 600 mSv</div>
      </div>
    )
  } else if (ind) body = <Reading ind={ind} />
  else body = <div className="tile-body"><div className="tv">{st.status}</div></div>
  return (
    <button className={`tile rise s${st.level} ${on ? 'on' : ''}`} style={{ ['--d' as string]: i }} onClick={onPick}>
      <div className="top"><span className="dot" />{st.name}{nasa && <span className="nasa-mark" title="A NASA-STD-3001 limit raises this level">NASA</span>}</div>
      {body}
    </button>
  )
}

function Verdict({ d, self, onCheck, onPick }: { d: CrewDetail; self: boolean; onCheck?: (k: CheckKind) => void; onPick: (s: SystemId) => void }) {
  const { setEmergency, setAskOpen } = useSession()
  const top = d.alerts[0]
  const first = d.crew.name.split(' ')[0]
  const learning = d.mission.learning
  const headline = learning ? 'Learning your normal.' : top ? top.title : `${self ? 'You are' : `${first} is`} within ${self ? 'your' : 'their'} normal.`
  const why = learning ? 'For the days before launch Canary only records how you sleep, react and feel when you are well. Alerts start at launch.'
    : top ? top.why : 'Nothing has left the personal range in the last three days.'
  const list = learning ? [] : attention(d.alerts, d.risks)
  const care = d.ops.care
  return (
    <div className="verdict">
      <div>
        <h1 className="rise">{headline}</h1>
        <p className="why rise">{why}</p>
        <p className="meta rise">{self ? `Hello, ${first}` : d.crew.name} · {d.mission.day_label} · {d.mission.place.name}</p>
      </div>
      {top && (
        <div className="col rise" style={{ gap: 12, ['--d' as string]: 2 }}>
          <ol className="steps">{top.todo.map(t => <li key={t}>{t}</li>)}</ol>
          <div className="row wrap">
            {top.test && onCheck && self && <button className="btn pri" onClick={() => onCheck(top.test as CheckKind)}>Take the reaction test</button>}
            {top.protocol && <button className="btn pri" onClick={() => setEmergency(true)}>Open the radiation protocol</button>}
            {top.sys && <button className="btn" onClick={() => onPick(top.sys as SystemId)}>Show on the body</button>}
            {self && <button className="btn ghost" onClick={() => setAskOpen(true)}><Icon name="ask" />Ask why</button>}
          </div>
        </div>
      )}
      <div className="attn rise" style={{ ['--d' as string]: 3 }}>
        <h3>Needs attention</h3>
        {list.length === 0 ? <p className="muted">Nothing needs attention</p> : (
          <ul>
            {list.map(a => (
              <li key={a.key} className={`s${a.level}`}>
                <button disabled={!a.sys} onClick={() => a.sys && onPick(a.sys as SystemId)}>
                  <span className="dot" /><span className="t">{a.title}</span>
                  {a.since !== undefined && <span className="small dim">since day {a.since}</span>}
                  <Letters ids={a.hazards} />
                </button>
              </li>
            ))}
          </ul>
        )}
        {care && <p className="small muted care-line">Recovering after {care.name} until day {care.until_day}.</p>}
      </div>
      {self && <div className="rise" style={{ ['--d' as string]: 3 }}><EvaReadiness d={d} compact /></div>}
    </div>
  )
}

function SystemPanel({ d, sys, onBack, onCheck }: { d: CrewDetail; sys: SystemId; onBack: () => void; onCheck?: (k: CheckKind) => void }) {
  const { catalog } = useSession()
  const st = d.systems[sys], info = d.system_info[sys]
  const alert = d.alerts.find(a => a.sys === sys)
  const risks = d.risks.filter(r => r.systems.includes(sys))
  const guide = catalog?.guide ?? {}
  const withGuide = st.indicators.filter(k => guide[k] && d.indicators[k])
  const action: Record<string, [CheckKind, string]> = { eyes: ['amsler', 'Do the Amsler grid'], heart: ['vitals', 'Enter vital signs'], brain: ['pvt', 'Take the reaction test'] }
  return (
    <div className="col sys-panel" style={{ gap: 22 }}>
      <button className="back rise" onClick={onBack}><Icon name="back" />Back to overview</button>
      <div className="rise" style={{ ['--d' as string]: 1 }}>
        <h1>{st.name}</h1>
        <p className="meta" style={{ textTransform: 'capitalize' }}>{st.area} · {info.hazard}</p>
        <div style={{ marginTop: 10 }}><Status level={st.level} /></div>
        {st.note && <p className="why">{st.note}</p>}
      </div>
      {sys === 'skin' && d.dose.career_msv !== undefined && <div className="rise" style={{ ['--d' as string]: 2 }}><RadiationBar d={d} /></div>}
      {alert && (
        <div className="col rise" style={{ gap: 10, ['--d' as string]: 2 }}>
          <h3>{alert.title}</h3>
          <ol className="steps">{alert.todo.map(t => <li key={t}>{t}</li>)}</ol>
        </div>
      )}
      {risks.map(r => <RiskBlock key={r.id} r={r} sys={sys} />)}
      <p className="muted rise" style={{ ['--d' as string]: 4 }}>{info.space}</p>
      {onCheck && (action[sys] || sys === 'brain') && (
        <div className="row wrap rise" style={{ ['--d' as string]: 5 }}>
          {action[sys] && <button className="btn pri" onClick={() => onCheck(action[sys][0])}>{action[sys][1]}</button>}
          {sys === 'brain' && <button className="btn" onClick={() => onCheck('mood')}>Mood check-in</button>}
        </div>
      )}
      {(withGuide.length > 0 || (sys === 'skin' && guide.radiation)) && (
        <div className="guide rise" style={{ ['--d' as string]: 5 }}>
          {(sys === 'skin' ? ['radiation'] : withGuide).map(k => <Guide key={k} name={d.indicators[k]?.name ?? 'Radiation dose'} g={guide[k]} />)}
        </div>
      )}
    </div>
  )
}

function RiskBlock({ r, sys }: { r: Risk; sys: SystemId }) {
  const lv = r.system_levels?.[sys] ?? r.level
  return (
    <div className={`risk rise s${lv}`}>
      <div className="risk-head"><span className="dot" /><h3>{r.name}</h3><Letters ids={r.hazards} /></div>
      <p className="small muted">
        {r.level === 0 ? 'Nothing raised' : `${TREND[r.trend]}${r.since_day !== null ? `, since day ${r.since_day}` : ''}`} · {DATA[r.data]}
      </p>
      {r.evidence.length > 0 && <ul className="risk-ev small">{r.evidence.map((e, i) => <li key={i}>{e.text}</li>)}</ul>}
      {r.hazard_links.length > 0 && <p className="small dim">{r.hazard_links.map(h => `${HAZARD_NAME[h.hazard]}: ${h.why}`).join(' ')}</p>}
    </div>
  )
}

/** "How to measure and why", folded. Each text names its source, or says there is none checked yet. */
function Guide({ name, g }: { name: string; g: GuideEntry }) {
  const src = (u: string | null | undefined) => (u ? <a className="item" href={u} target="_blank" rel="noreferrer">Source</a> : <span className="dim">No source checked yet</span>)
  return (
    <details className="how">
      <summary>How to measure and why · {name}</summary>
      <dl>
        <dt>How</dt><dd>{g.how} {src(g.sources.how)}</dd>
        <dt>What space does</dt><dd>{g.effect} {src(g.sources.effect)}</dd>
        <dt>Green</dt><dd>{g.actions.green}</dd>
        <dt>Amber</dt><dd>{g.actions.amber}</dd>
        <dt>Red</dt><dd>{g.actions.red} {g.sources.actions.length ? g.sources.actions.map((u, i) => <a key={u} className="item" href={u} target="_blank" rel="noreferrer">Source {i + 1}</a>) : <span className="dim">No source checked yet</span>}</dd>
        <dt>How often</dt><dd>{g.frequency}</dd>
      </dl>
    </details>
  )
}

export function Blood({ d }: { d: CrewDetail }) {
  const b = d.blood, w = 360, h = 120
  const lo = Math.min(b.range.min, ...b.lymphocytes) * 0.9, hi = Math.max(b.range.max, ...b.lymphocytes) * 1.05
  const X = (i: number) => 14 + (i / (b.lymphocytes.length - 1)) * (w - 28), Y = (v: number) => h - 20 - ((v - lo) / (hi - lo)) * (h - 30)
  return (
    <div className="rise" style={{ ['--d' as string]: 3 }}>
      <div className="lbl">Lymphocytes · real NASA data (OSD-569, Inspiration4)</div>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" className="chart" style={{ marginTop: 8 }}>
        <rect x="14" width={w - 28} y={Y(b.range.max)} height={Y(b.range.min) - Y(b.range.max)} fill="var(--surface-2)" />
        <path d={b.lymphocytes.map((v, i) => `${i ? 'L' : 'M'}${X(i)},${Y(v)}`).join('')} fill="none" stroke="var(--physical)" strokeWidth="1.8" />
        {b.lymphocytes.map((v, i) => <circle key={i} cx={X(i)} cy={Y(v)} r="2.5" fill="var(--physical)" />)}
        {b.timepoints.map((t, i) => <text key={t} x={X(i)} y={h - 4} textAnchor="middle">{t}</text>)}
      </svg>
      <div className="small dim">Shaded band: reference range.</div>
    </div>
  )
}
