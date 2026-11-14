// Mission plan: the itinerary. Every place change re-adapts goals, alerts, radiation,
// communication delay and Guided Response automatically, because the backend asks the
// plan where the crew is on each day.
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { Leg, Plan } from '../api/types'
import { Icon, Loading } from '../components/ui'
import { useSession } from '../state/session'

const ADAPT: Record<string, string[]> = {
  g0: ['Exercise goal: 2 hours a day (resistance + treadmill or bike)', 'Bone loss model at full rate', 'Guided Response uses 0 g steps: restraints, tethers, floating fluids', 'Space-sickness rule active in the first 72 hours'],
  gp: ['Exercise goal: 1 hour of resistance, suited walks', 'Re-adaptation alert in the first 30 days after 0 g', 'Bone loss at about 40% of the 0 g rate', 'Outside activity depends on space weather; partial-gravity steps'],
  g1: ['Training and recovery goals', 'Bone slowly recovers', 'Guided Response uses Earth steps', 'Before launch: baseline only, no alerts'],
}

export default function MissionPlan() {
  const { mission, catalog, bump, toast, setStep } = useSession()
  const [plan, setPlan] = useState<Plan | null>(null)
  const [legs, setLegs] = useState<Leg[]>([])
  const [name, setName] = useState('')
  const [err, setErr] = useState('')
  const [day, setDay] = useState<number | null>(null)
  useEffect(() => { api.plan().then(p => { setPlan(p); setLegs(p.legs); setName(p.name) }) }, [])
  useEffect(() => { if (mission) setDay(mission.day) }, [mission])
  const dirty = useMemo(() => plan && (JSON.stringify(legs) !== JSON.stringify(plan.legs) || name !== plan.name), [plan, legs, name])
  if (!plan || !mission || !catalog || day === null) return <Loading what="mission plan" />

  const lo = plan.legs[0].start, hi = plan.legs[plan.legs.length - 1].end
  const span = hi - lo + 1
  const pct = (d: number) => `${(100 * (Math.min(hi, Math.max(lo, d)) - lo + 0.5)) / span}%`
  const goTo = async (d: number) => { await api.setDay(d); bump() }
  const place = catalog.locations[mission.location]
  const set = (i: number, k: keyof Leg, v: string) => setLegs(ls => ls.map((l, j) => j === i ? { ...l, [k]: k === 'start' || k === 'end' ? Number(v) : v } : l))
  const save = async () => {
    try { const p = await api.savePlan(name, legs); setPlan(p); setLegs(p.legs); setErr(''); bump(); toast('Mission plan saved. Everything re-adapted.') }
    catch (e) { setErr((e as Error).message) }
  }
  const preset = async (k: string) => { const p = await api.usePreset(k); setPlan(p); setLegs(p.legs); setName(p.name); setErr(''); bump(); toast(`Plan: ${p.name}`) }

  return (
    <div className="page">
      <div className="head rise">
        <div><span className="eyebrow">Mission plan</span><h1 style={{ marginTop: 6 }}>{plan.name}</h1>
          <p className="sub">Day {lo} to {hi} · {plan.legs.length} legs. Canary adapts to wherever the plan puts the crew.</p></div>
        <div className="row right wrap">
          <span className="small muted">Start from</span>
          {Object.entries(plan.presets).map(([k, n]) => <button key={k} className={`btn sm ${plan.preset === k ? '' : 'ghost'}`} onClick={() => preset(k)}>{n}</button>)}
        </div>
      </div>

      <section className="detail-card rise" style={{ ['--d' as string]: 1 }}>
        <div className="timeline" style={{ marginTop: 22 }}>
          {plan.legs.map((l, i) => (
            <button key={i} className={`seg p-${l.location}`} style={{ flex: l.end - l.start + 1 }} onClick={() => goTo(l.start)} title={`Go to day ${l.start}`}>
              <b>{catalog.locations[l.location].name}</b><span>{l.label || ''} · {l.end - l.start + 1} d</span>
            </button>
          ))}
          <i className="now" style={{ left: pct(day) }} data-l={`Day ${day}`} />
        </div>
        <div className="row" style={{ marginTop: 18, gap: 16 }}>
          <span className="small muted num">Day {lo}</span>
          <input type="range" min={lo} max={hi} value={day} onChange={e => setDay(Number(e.target.value))} onPointerUp={() => goTo(day)} onKeyUp={() => goTo(day)} aria-label="Mission day" />
          <span className="small muted num">Day {hi}</span>
        </div>
        <div className="row wrap" style={{ marginTop: 10 }}>
          <span className="small dim">Drag to any day, or click a leg. Every screen follows.</span>
          {mission.custom_day && <button className="btn sm right" onClick={() => setStep(mission.step)}>Back to the demo story</button>}
        </div>
      </section>

      <section className="grid g2">
        <div className={`detail-card rise p-${mission.location}`} style={{ ['--d' as string]: 2, borderLeft: '3px solid var(--pc)' }}>
          <span className="eyebrow">{mission.day_label}{mission.location_override ? ' · simulated place' : ''}</span>
          <h2 style={{ marginTop: 6 }}>{place.name}: {mission.leg.label}</h2>
          <dl className="adapt" style={{ marginTop: 16 }}>
            <dt>Gravity</dt><dd>{place.gravity}</dd>
            <dt>Earth replies</dt><dd>{place.reply}</dd>
            <dt>Radiation</dt><dd>{place.dose_rate} mSv/day</dd>
            <dt>Hospital</dt><dd>{place.hospital}</dd>
            <dt>This leg</dt><dd>Day {mission.leg.day_in_leg} of {mission.leg.length}{mission.leg.next ? `, next: ${mission.leg.next.label || catalog.locations[mission.leg.next.location].name} in ${mission.leg.days_to_next} days` : ''}</dd>
          </dl>
        </div>
        <div className="detail-card rise" style={{ ['--d' as string]: 3 }}>
          <h2>What Canary changes here</h2>
          <ul className="steps" style={{ marginTop: 16 }}>
            {ADAPT[place.gravity_key].map(t => <li key={t}>{t}</li>)}
            <li>{place.reply === 'Live' ? 'Messages and reports reach Earth live' : `Messages, briefings and reports wait ${place.reply} each way`}</li>
          </ul>
        </div>
      </section>

      <section className="detail-card rise" style={{ ['--d' as string]: 4 }}>
        <div className="section-head"><h2>Itinerary</h2><span className="sub">Day 0 is launch. Negative days are pre-flight.</span></div>
        <label className="field" style={{ maxWidth: 420, marginBottom: 16 }}><span className="lbl">Plan name</span><input value={name} onChange={e => setName(e.target.value)} /></label>
        <div className="legs">
          <span className="h">Place</span><span className="h">From day</span><span className="h">To day</span><span className="h">What happens</span><span />
          {legs.map((l, i) => (
            <div key={i} style={{ display: 'contents' }}>
              <select className="in" value={l.location} onChange={e => set(i, 'location', e.target.value)}>
                {Object.entries(catalog.locations).map(([k, p]) => <option key={k} value={k}>{p.name}</option>)}
              </select>
              <input className="in num" type="number" value={l.start} onChange={e => set(i, 'start', e.target.value)} aria-label="From day" />
              <input className="in num" type="number" value={l.end} onChange={e => set(i, 'end', e.target.value)} aria-label="To day" />
              <input className="in" value={l.label} onChange={e => set(i, 'label', e.target.value)} placeholder="e.g. Cruise to Mars" aria-label="What happens" />
              <button className="btn sm ghost" onClick={() => setLegs(ls => ls.filter((_, j) => j !== i))} disabled={legs.length < 2} aria-label="Remove leg"><Icon name="close" /></button>
            </div>
          ))}
        </div>
        <div className="row wrap" style={{ marginTop: 16 }}>
          <button className="btn" onClick={() => { const last = legs[legs.length - 1]; setLegs([...legs, { location: 'earth', start: last.end + 1, end: last.end + 30, label: '' }]) }}><Icon name="plus" />Add leg</button>
          <span className="grow" />
          {err && <span className="small" style={{ color: 'var(--act)' }}>{err}</span>}
          <button className="btn ghost" disabled={!dirty} onClick={() => { setLegs(plan.legs); setName(plan.name); setErr('') }}>Discard</button>
          <button className="btn pri" disabled={!dirty} onClick={save}>Save plan</button>
        </div>
      </section>
    </div>
  )
}
