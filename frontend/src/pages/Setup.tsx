// Mission setup: the first thing after the intro. Destination, length, crew, review, launch.
// Same visual language as the intro (black, starfield, text that rises out of a blur). The plan it builds is the
// same list of legs the mission plan page edits; the three defaults reproduce the backend presets exactly.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { Leg } from '../api/types'
import { Dot } from '../components/People'
import Stars from '../components/Stars'
import { CanaryMark, Icon, Loading } from '../components/ui'
import * as rules from '../lib/validate'
import { useSession } from '../state/session'

type Dest = 'mars' | 'iss' | 'moon'
type Vals = Record<string, number>
interface Field { key: string; label: string; hint: string; min: number; max: number }
interface Step { loc: string; key: string; label: string; title?: string; optional?: 'return' }
/** A pressurized rover traverse cut out of the surface stay: it starts `at` days into the stay and lasts `len` days. */
interface Rover { loc: string; at: number; len: number; label: string }
interface Spec { name: string; line: string; fields: Field[]; defaults: Vals; steps: Step[]; returnFields?: Field[]; returnDefaults?: Vals; rover?: Rover }

// First step is always pre-flight training, which ends on day -1; day 0 is launch.
const SPECS: Record<Dest, Spec> = {
  mars: {
    name: 'Mars reference mission',
    line: 'Gale crater. Months of deep space first, then Earth is too far to help in time.',
    fields: [
      { key: 'training', label: 'Pre-flight training', hint: 'Days on Earth, learning everyone\'s normal', min: 7, max: 180 },
      { key: 'launch', label: 'Launch to orbit', hint: 'Days until the cruise begins', min: 3, max: 14 },
      { key: 'cruise', label: 'Cruise to Mars', hint: 'Days in deep space', min: 120, max: 300 },
      { key: 'stay', label: 'Surface stay', hint: 'Days on Mars', min: 30, max: 800 },
    ],
    rover: { loc: 'mars_rover', at: 90, len: 14, label: 'Pressurized rover traverse to Mount Sharp' },
    defaults: { training: 60, launch: 4, cruise: 206, stay: 511, back: 206, recovery: 60 },
    returnFields: [
      { key: 'back', label: 'Cruise back to Earth', hint: 'Days in deep space', min: 120, max: 300 },
      { key: 'recovery', label: 'Recovery on Earth', hint: 'Days of rehabilitation', min: 14, max: 180 },
    ],
    steps: [
      { loc: 'earth', key: 'training', label: 'Pre-flight training and baseline' },
      { loc: 'rocket', key: 'launch', label: 'Launch and first 72 hours' },
      { loc: 'transit', key: 'cruise', label: 'Cruise to Mars' },
      { loc: 'mars', key: 'stay', label: 'Surface stay, Gale crater' },
      { loc: 'transit', key: 'back', label: 'Cruise back to Earth', title: 'Return cruise', optional: 'return' },
      { loc: 'earth', key: 'recovery', label: 'Recovery and rehabilitation', optional: 'return' },
    ],
  },
  iss: {
    name: 'Six months on the ISS',
    line: 'Low Earth orbit. Weightless, and Earth is close enough to help.',
    fields: [
      { key: 'training', label: 'Pre-flight training', hint: 'Days on Earth, learning everyone\'s normal', min: 7, max: 180 },
      { key: 'launch', label: 'Launch and docking', hint: 'Days to reach the station', min: 1, max: 7 },
      { key: 'stay', label: 'Station stay', hint: 'Days in orbit', min: 30, max: 365 },
      { key: 'back', label: 'Undocking and landing', hint: 'Days to come home', min: 1, max: 3 },
      { key: 'recovery', label: 'Recovery on Earth', hint: 'Days of rehabilitation', min: 14, max: 180 },
    ],
    defaults: { training: 60, launch: 2, stay: 180, back: 1, recovery: 88 },
    steps: [
      { loc: 'earth', key: 'training', label: 'Pre-flight training and baseline' },
      { loc: 'rocket', key: 'launch', label: 'Launch and docking' },
      { loc: 'iss', key: 'stay', label: 'Expedition on the station' },
      { loc: 'rocket', key: 'back', label: 'Undocking and landing', title: 'Return' },
      { loc: 'earth', key: 'recovery', label: 'Recovery and rehabilitation' },
    ],
  },
  moon: {
    name: 'Lunar surface mission',
    line: 'The lunar south pole. Partial gravity, and Earth answers within seconds.',
    fields: [
      { key: 'training', label: 'Pre-flight training', hint: 'Days on Earth, learning everyone\'s normal', min: 7, max: 180 },
      { key: 'launch', label: 'Transfer to the Moon', hint: 'Days from launch to landing', min: 3, max: 8 },
      { key: 'stay', label: 'Surface stay', hint: 'Days on the Moon', min: 7, max: 90 },
      { key: 'back', label: 'Return trip', hint: 'Days back to Earth', min: 3, max: 8 },
      { key: 'recovery', label: 'Recovery on Earth', hint: 'Days of rehabilitation', min: 14, max: 180 },
    ],
    rover: { loc: 'moon_rover', at: 15, len: 5, label: 'Pressurized rover traverse' },
    defaults: { training: 60, launch: 5, stay: 30, back: 5, recovery: 81 },
    steps: [
      { loc: 'earth', key: 'training', label: 'Pre-flight training and baseline' },
      { loc: 'rocket', key: 'launch', label: 'Launch and lunar transit' },
      { loc: 'moon', key: 'stay', label: 'Surface stay, south pole' },
      { loc: 'rocket', key: 'back', label: 'Return to Earth', title: 'Return' },
      { loc: 'earth', key: 'recovery', label: 'Recovery' },
    ],
  },
}
const DESTS: Dest[] = ['mars', 'iss', 'moon']
const STEP_NAMES = ['Destination', 'Timeline', 'Crew', 'Review']

interface Seg extends Leg { title?: string }

/** The rover needs a stay with at least a day on the surface before and after it. */
const roverFits = (dest: Dest, stay: number) => { const r = SPECS[dest].rover; return !!r && stay >= r.len + 2 }

/** Turn the numbers into legs: training ends on day -1, launch is day 0, every leg starts the day after the last. */
export function buildLegs(dest: Dest, v: Vals, withReturn: boolean, withRover = false): Seg[] {
  const legs: Seg[] = []
  let day = -v.training
  for (const s of SPECS[dest].steps) {
    if (s.optional === 'return' && !withReturn) continue
    const len = v[s.key]
    const r = SPECS[dest].rover
    const cut = withRover && r && s.key === 'stay' && roverFits(dest, len) ? Math.min(r.at, len - r.len - 1) : 0  // days of stay before the rover
    if (cut && r) {
      legs.push({ location: s.loc, start: day, end: day + cut - 1, label: s.label, title: s.title })
      legs.push({ location: r.loc, start: day + cut, end: day + cut + r.len - 1, label: r.label })
      legs.push({ location: s.loc, start: day + cut + r.len, end: day + len - 1, label: s.label, title: s.title })
    } else legs.push({ location: s.loc, start: day, end: day + len - 1, label: s.label, title: s.title })
    day += len
    if (s.key === 'training') day = 0
  }
  return legs
}

export default function Setup() {
  const { catalog, setMission, bump } = useSession()
  const nav = useNavigate()
  const [step, setStep] = useState(0)
  const [dest, setDest] = useState<Dest>('mars')
  const [vals, setVals] = useState<Record<Dest, Vals>>({ mars: { ...SPECS.mars.defaults }, iss: { ...SPECS.iss.defaults }, moon: { ...SPECS.moon.defaults } })
  const [withReturn, setWithReturn] = useState(false)
  const [withRover, setWithRover] = useState(true)
  const [name, setName] = useState(SPECS.mars.name)
  const [nameEdited, setNameEdited] = useState(false)
  const [phase, setPhase] = useState<'edit' | 'launching'>('edit')
  const [count, setCount] = useState(3)
  const [err, setErr] = useState('')
  const [fieldErrs, setFieldErrs] = useState<Record<string, string>>({})
  const [blocked, setBlocked] = useState(false)
  const busy = useRef(false)
  const badRef = useRef(false)
  badRef.current = Object.keys(fieldErrs).length > 0
  /** A duration box reports its error here. While one is wrong the person cannot move on or start the mission. */
  const report = useCallback((key: string, message: string | null) => {
    setFieldErrs(e => { if ((e[key] ?? null) === message) return e; const n = { ...e }; if (message) n[key] = message; else delete n[key]; return n })
  }, [])
  /** True when it is fine to go on. Otherwise says why and puts the focus on the first wrong box. */
  const clear = useCallback(() => {
    if (!badRef.current) { setBlocked(false); return true }
    setBlocked(true)
    document.querySelector<HTMLElement>('.numfield [aria-invalid="true"]')?.focus()
    return false
  }, [])

  const v = vals[dest]
  const legs = useMemo(() => buildLegs(dest, v, dest === 'mars' && withReturn, withRover), [dest, v, withReturn, withRover])

  const pick = (d: Dest) => {
    setDest(d)
    if (!nameEdited) setName(SPECS[d].name)
  }
  const setVal = (key: string, n: number) => setVals(all => ({ ...all, [dest]: { ...all[dest], [key]: n } }))

  /** Save the plan, then (optionally) play the launch before landing on the crew page. */
  const launch = useCallback(async (planName: string, planLegs: Seg[], countdown: boolean) => {
    if (busy.current || !clear()) return
    busy.current = true
    setErr('')
    if (countdown) { setCount(3); setPhase('launching') }
    try {
      const clean: Leg[] = planLegs.map(({ location, start, end, label }) => ({ location, start, end, label }))
      const wait = countdown ? new Promise(r => setTimeout(r, 2300)) : Promise.resolve()
      const [m] = await Promise.all([api.setup(planName.trim() || 'Mission plan', clean), wait])
      try { sessionStorage.setItem('canary.intro', '1') } catch { /* storage blocked */ }
      setMission(m)
      bump()
      nav('/crew')
    } catch (e) {
      busy.current = false
      setPhase('edit')
      setErr((e as Error).message)
    }
  }, [bump, nav, setMission, clear])

  const useDemo = () => launch(SPECS.mars.name, buildLegs('mars', SPECS.mars.defaults, false, true), false)
  const next = () => { if (step < 3 && clear()) setStep(step + 1) }
  const back = () => { if (step > 0) setStep(step - 1) }

  // Countdown 3, 2, 1 while the plan saves.
  useEffect(() => {
    if (phase !== 'launching') return
    const t = setInterval(() => setCount(c => Math.max(0, c - 1)), 640)
    return () => clearInterval(t)
  }, [phase])

  // Enter advances, unless a button has focus (then Enter presses that button).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Enter' || phase !== 'edit') return
      const el = document.activeElement as HTMLElement | null
      if (el && (el.tagName === 'BUTTON' || el.tagName === 'A')) return
      if (!clear()) return
      el?.blur()
      if (step < 3) setStep(s => s + 1)
      else launch(name, legs, true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [phase, step, launch, name, legs, clear])

  if (!catalog) return <div className="intro"><Loading what="mission setup" /></div>
  const last = legs[legs.length - 1].end
  const place = catalog.locations[dest]

  const heads = [
    { h: 'Where is this mission going?', p: 'Everything Canary watches adapts to the place: gravity, radiation, how far Earth is.' },
    { h: 'How long?', p: 'Set the length of each part. The timeline below follows as you change the numbers.' },
    { h: 'Your crew', p: 'Four people, each with their own normal.' },
    { h: 'Ready for launch?', p: `${name || 'Your mission'}, ${last + 1} days from launch to the end of the plan.` },
  ][step]

  return (
    <div className="intro setup">
      <Stars />
      <div className="row reveal" style={{ padding: '24px 7vw 0' }}>
        <span className="brand"><CanaryMark size={26} />CANARY</span>
        <span className="small dim setup-tag">Mission setup</span>
        <button className="btn sm ghost right" onClick={useDemo} disabled={phase !== 'edit'}>Skip, use the demo story<Icon name="chev" /></button>
      </div>

      <div className="setup-stage">
        <div className="setup-head" key={`h${step}`}>
          <span className="kicker reveal">Step {step + 1} of 4 · {STEP_NAMES[step]}</span>
          <h1 className="reveal d1">{heads.h}</h1>
          <p className="lead reveal d2">{heads.p}</p>
        </div>

        {err && <p className="small" style={{ color: 'var(--act)' }} role="alert">Could not save the plan: {err}</p>}
        <div className="setup-body" key={`b${step}`}>
          {step === 0 && (
            <div className="dest-grid" role="radiogroup" aria-label="Destination">
              {DESTS.map((d, i) => {
                const p = catalog.locations[d]
                return (
                  <button key={d} role="radio" aria-checked={dest === d} className={`dest rise p-${d} ${dest === d ? 'on' : ''}`} style={{ ['--d' as string]: i + 1 }} onClick={() => pick(d)}>
                    <span className="dest-top"><h2>{p.name}</h2><span className="dest-check">{dest === d && <Icon name="check" size={16} />}</span></span>
                    <span className="small muted">{SPECS[d].line}</span>
                    <dl>
                      <dt>Gravity</dt><dd className="num">{p.gravity}</dd>
                      <dt>Earth replies</dt><dd className="num">{p.reply}</dd>
                      <dt>Radiation</dt><dd className="num">{p.dose_rate} mSv/day</dd>
                    </dl>
                  </button>
                )
              })}
            </div>
          )}

          {step === 1 && (
            <div className="setup-cols fields">
              <div className="col rise" style={{ ['--d' as string]: 1, gap: 18 }}>
                <label className="field"><span className="lbl">Mission name</span>
                  <input value={name} maxLength={80} onChange={e => { setName(e.target.value); setNameEdited(true) }} />
                  <span className="hint">Up to 80 characters. Left empty, the plan is called Mission plan.</span></label>
                {SPECS[dest].fields.map(f => <NumField key={f.key} f={f} value={v[f.key]} onChange={n => setVal(f.key, n)} report={report} />)}
                {SPECS[dest].rover && (
                  <div className="col" style={{ gap: 4 }}>
                    <button className="row small toggle" onClick={() => setWithRover(!withRover)} aria-pressed={withRover} disabled={!roverFits(dest, v.stay)}>
                      <span className={`switch ${withRover && roverFits(dest, v.stay) ? 'on' : ''}`} />Include a rover traverse ({SPECS[dest].rover!.len} days)
                    </button>
                    {!roverFits(dest, v.stay) && <span className="small dim">The surface stay needs at least {SPECS[dest].rover!.len + 2} days for a rover traverse.</span>}
                  </div>
                )}
                {dest === 'mars' && (
                  <>
                    <button className="row small toggle" onClick={() => setWithReturn(!withReturn)} aria-pressed={withReturn}>
                      <span className={`switch ${withReturn ? 'on' : ''}`} />Include the return trip
                    </button>
                    {withReturn && SPECS.mars.returnFields!.map(f => <NumField key={f.key} f={f} value={v[f.key]} onChange={n => setVal(f.key, n)} report={report} />)}
                  </>
                )}
                {blocked && Object.keys(fieldErrs).length > 0 && <p className="form-err" role="alert">Fix the duration marked above before you continue.</p>}
              </div>
              <div className="rise" style={{ ['--d' as string]: 2 }}>
                <Preview legs={legs} names={Object.fromEntries(Object.entries(catalog.locations).map(([k, p]) => [k, p.name]))} />
                <p className="small dim" style={{ marginTop: 10 }}>{place.name}: {place.what}</p>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="setup-crew">
              {catalog.crew.map((c, i) => (
                <div key={c.id} className="rise setup-person" style={{ ['--d' as string]: i + 1 }}>
                  <Dot p={c} size="xl" />
                  <b>{c.name}</b><span className="small muted">{c.role}</span>
                </div>
              ))}
              <p className="setup-lock rise" style={{ ['--d' as string]: 6 }}>
                <Icon name="lock" size={18} />
                <span>Each person's health stays private behind their own 4-digit PIN. The crew page shows goals and hazards, never diagnoses.</span>
              </p>
            </div>
          )}

          {step === 3 && (
            <div className="setup-cols">
              <div className="col rise" style={{ ['--d' as string]: 1, gap: 14 }}>
                <dl className="setup-sum">
                  <dt>Mission</dt><dd>{name || 'Mission plan'}</dd>
                  <dt>Destination</dt><dd>{place.name}</dd>
                  <dt>Launch</dt><dd className="num">Day 0, after {v.training} days of training</dd>
                  <dt>Length</dt><dd className="num">{last + 1} days from launch</dd>
                  <dt>Crew</dt><dd>{catalog.crew.map(c => c.name.split(' ')[0]).join(', ')}</dd>
                </dl>
                <button className="btn" style={{ alignSelf: 'flex-start' }} onClick={useDemo} disabled={phase !== 'edit'}>Use the demo story (Mars)</button>
              </div>
              <div className="rise" style={{ ['--d' as string]: 2 }}>
                <Preview legs={legs} names={Object.fromEntries(Object.entries(catalog.locations).map(([k, p]) => [k, p.name]))} />
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="intro-nav setup-nav">
        <div className="stepbars">
          {STEP_NAMES.map((n, k) => (
            <button key={n} className={`stepbar ${k < step ? 'done' : k === step ? 'on' : ''}`} onClick={() => k < step && setStep(k)} aria-label={`Step ${k + 1}: ${n}`} aria-current={k === step} disabled={k > step}><i /></button>
          ))}
        </div>
        <span className="grow" />
        <button className="btn ghost lg" onClick={back} disabled={step === 0}><Icon name="back" />Back</button>
        {step < 3
          ? <button className="btn pri lg" onClick={next}>Next<Icon name="chev" /></button>
          : <button className="btn pri lg" onClick={() => launch(name, legs, true)}>Start the mission<Icon name="chev" /></button>}
      </div>

      {phase === 'launching' && <Launch name={name || 'Mission'} legs={legs} count={count} names={Object.fromEntries(Object.entries(catalog.locations).map(([k, p]) => [k, p.name]))} />}
    </div>
  )
}

/** A slider and a number box for the same value. The box keeps what you type: a wrong number is not changed behind
 *  your back, it shows what is wrong under the box and stops the setup from moving on until it is fixed. */
function NumField({ f, value, onChange, report }: { f: Field; value: number; onChange: (n: number) => void; report: (key: string, message: string | null) => void }) {
  const [draft, setDraft] = useState<string | null>(null)
  const check = rules.number(f.label, { min: f.min, max: f.max, unit: 'days', integer: true })
  const err = draft === null ? null : check(draft)
  useEffect(() => { report(f.key, err); return () => report(f.key, null) }, [f.key, err, report])
  const id = `num-${f.key}`
  return (
    <div className="numfield">
      <div className="row"><label className="lbl grow" htmlFor={id}>{f.label}</label>
        <input id={id} className="in num" type="text" inputMode="numeric" value={draft ?? value} autoComplete="off" aria-invalid={err ? true : undefined} aria-describedby={`${id}-msg`}
          onChange={e => { setDraft(e.target.value); if (!check(e.target.value)) onChange(Number(e.target.value.trim().replace(',', '.'))) }}
          onBlur={() => { if (!err) setDraft(null) }} />
        <span className="small dim">days</span>
      </div>
      <input type="range" min={f.min} max={f.max} value={value} onChange={e => { setDraft(null); onChange(Number(e.target.value)) }} aria-label={`${f.label}, slider`} />
      <span className={err ? 'small err' : 'small dim'} id={`${id}-msg`}>{err ?? f.hint}</span>
    </div>
  )
}

/** The itinerary as a bar that re-proportions smoothly when the numbers change. */
function Preview({ legs, names, now }: { legs: Seg[]; names: Record<string, string>; now?: string }) {
  const lo = legs[0].start, hi = legs[legs.length - 1].end, span = hi - lo + 1
  const at = (d: number) => `${(100 * (d - lo + 0.5)) / span}%`
  return (
    <div className="preview">
      <div className="timeline">
        {legs.map((l, i) => (
          <div key={i} className={`seg p-${l.location}`} style={{ flexGrow: l.end - l.start + 1 }} title={`${l.label}: day ${l.start} to ${l.end}`}>
            <b>{l.title ?? names[l.location]}</b><span>{l.end - l.start + 1} d</span>
          </div>
        ))}
        <i className="now" style={{ left: now ?? at(0) }} data-l="Launch" />
      </div>
      <div className="preview-total row wrap">
        <span className="num">Launch on day 0 · {hi + 1} days in all</span>
        <span className="small dim right">{-lo} days of training first</span>
      </div>
    </div>
  )
}

/** The launch: a 3-2-1 over the timeline while the "now" marker sweeps to day 0. */
function Launch({ name, legs, count, names }: { name: string; legs: Seg[]; count: number; names: Record<string, string> }) {
  const [sweep, setSweep] = useState(false)
  useEffect(() => { const r = requestAnimationFrame(() => requestAnimationFrame(() => setSweep(true))); return () => cancelAnimationFrame(r) }, [])
  const lo = legs[0].start, span = legs[legs.length - 1].end - lo + 1
  return (
    <div className="launch" role="status" aria-live="polite">
      <span className="kicker reveal">Launching</span>
      <h2 className="reveal d1">{name}</h2>
      <div className="countdown" aria-label={count > 0 ? String(count) : 'Liftoff'}>
        {count > 0 ? <span key={count} className="count-n num">{count}</span> : <span key="go" className="count-go">Liftoff</span>}
      </div>
      <div className="launch-tl reveal d2">
        <Preview legs={legs} names={names} now={sweep ? `${(100 * (0 - lo + 0.5)) / span}%` : '0%'} />
      </div>
    </div>
  )
}
