// Mission plan: the itinerary mission control registered, read for health. Pick a leg to see
// what the body faces there and what Canary changes. Editing the plan belongs to the admin flow.
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Link } from 'react-router-dom'
import type { Place, PlanConditions, ProtocolLibrary } from '../api/types'
import { protocolPath } from './Protocols'
import Hazards from '../components/Hazards'
import Timeline from '../components/Timeline'
import { LineChart, Loading } from '../components/ui'
import { useApi, useSession } from '../state/session'

const BODY: Record<string, string[]> = {
  g0: ['Bone loss at the full 0 g rate, about 1% a month without exercise', 'Fluids shift toward the head: watch the eyes', 'Space sickness is common in the first 72 hours'],
  gp: ['Re-adaptation to weight in the first 30 days after 0 g: dizziness when standing', 'Bone loss slows to about 40% of the 0 g rate', 'Fine, sharp dust outside'],
  g1: ['Bone slowly recovers', 'Baseline training: Canary learns each person\'s normal'],
}
const EXERCISE: Record<string, string> = {
  g0: '2 hours a day, resistance plus treadmill or bike',
  gp: '1 hour of resistance and suited walks',
  g1: 'Training and recovery goals; no alerts before launch, only baselines',
}
const EVA: Record<string, string> = {
  none: 'No EVA here',
  microgravity: 'Spacewalks in 0 g, each person cleared by the medical team',
  surface: 'Surface walks, each person cleared by the medical team; space weather decides the day',
}

/** The Protocols pages that apply to a leg, from the same rules the Protocols page uses for today (no personal data). */
function legProtocols(c: PlanConditions, i: number, place: Omit<Place, 'id'>): string[] {
  const leg = c.legs[i], prev = c.legs[i - 1]
  const out: string[] = []
  if (leg.location !== 'earth') out.push('rad', 'dose')
  if (leg.location !== 'earth' && place.eva && place.eva !== 'none') out.push('eva')
  if (leg.location === 'rocket') out.push('sickness')
  if (prev && prev.gravity_key === 'g0' && leg.gravity_key === 'gp') out.push('regravity')
  if (leg.ridge.find(h => h.id === 'E' && h.level >= 2)) out.push('air')
  if (place.delay_s > 60) out.push('delay')
  return out
}

export default function MissionPlan() {
  const { mission, catalog } = useSession()
  const { data: c } = useApi<PlanConditions>(() => api.conditions(), [])
  const { data: lib } = useApi<ProtocolLibrary>(() => api.protocolLibrary(), [])
  const [sel, setSel] = useState<number | null>(null)
  // The leg the crew is on now is always the one open by default, also after the clock moves.
  const nowLeg = c ? Math.max(0, c.leg_index) : null
  useEffect(() => { if (nowLeg !== null) setSel(nowLeg) }, [nowLeg, c?.today])
  if (!c || !mission || !catalog || sel === null) return <Loading what="mission plan" />

  const leg = c.legs[sel]
  const place = catalog.locations[leg.location]
  const last = c.legs[c.legs.length - 1].end
  const when = c.today > leg.end ? 'done' : c.today >= leg.start ? `now, day ${c.today - leg.start + 1} of ${leg.days}` : `starts in ${leg.start - c.today} days`
  const d = c.dose
  const upcoming = c.legs.map((_, i) => i).filter(i => i > sel && c.legs[i].start > c.today).slice(0, 3)
  const crosses = d.series.find(([, v]) => v >= d.limit_msv)

  return (
    <div className="page">
      <div className="head rise">
        <div>
          <h1>{c.name}</h1>
          <p className="sub">Pick a leg to see what it does to the body and what Canary changes.</p>
        </div>
      </div>

      <section className="rise" style={{ ['--d' as string]: 1 }}>
        <Timeline legs={c.legs} places={catalog.locations} now={c.today} nowLabel={mission.day_label} selected={sel} onSelect={setSel} />
      </section>

      <section className={`rise p-${leg.location}`} style={{ ['--d' as string]: 2 }} key={sel}>
        <div className="section-head">
          <span className="pc-dot" />
          <h2>{leg.label || place.name}</h2>
          <span className="sub">{place.name} · day {leg.start} to {leg.end} · {when}</span>
        </div>
        <p className="leg-facts">
          <span>{place.gravity}</span>
          <span>{place.dose_rate} mSv a day</span>
          <span>Earth replies {place.reply === 'Live' ? 'live' : `in ${place.reply}`}</span>
          <span>Hospital: {place.hospital.toLowerCase()}</span>
        </p>
        <ul className="bul" style={{ marginTop: 14 }}>{BODY[leg.gravity_key].map(t => <li key={t}>{t}</li>)}</ul>

        <h3 className="sub-h">Hazards on this leg</h3>
        <Hazards items={leg.ridge} compact />

        <h3 className="sub-h">What the crew does here</h3>
        <dl className="adapt">
          <dt>Exercise</dt><dd>{EXERCISE[leg.gravity_key]}</dd>
          {leg.location !== 'earth' && <><dt>EVA</dt><dd>{EVA[place.eva ?? 'none']}</dd></>}
          <dt>Messages</dt><dd>{place.reply === 'Live' ? 'Reach Earth live' : `Wait ${place.reply} each way`}</dd>
          <dt>Guided Response</dt><dd>Steps for {place.gravity}</dd>
        </dl>
        {lib && legProtocols(c, sel, place).length > 0 && (
          <ul className="plist" style={{ marginTop: 22 }}>
            {legProtocols(c, sel, place).map(id => {
              const p = [...lib.emergency, ...lib.operational].find(x => x.id === id)
              const f = sel === c.leg_index ? lib.in_force.find(x => x.id === id) : undefined
              return p && (
                <li key={id} className={f ? `s${f.level}` : ''}>
                  <Link to={protocolPath(id)} className="prow">{f && <span className="dot" />}<span className="grow"><b>{p.name}</b><span className="muted">{f ? f.reason : p.when[0]}</span></span></Link>
                </li>
              )
            })}
          </ul>
        )}

        {upcoming.length > 0 && (
          <>
            <h3 className="sub-h">Upcoming legs</h3>
            <ul className="plist">
              {upcoming.map(i => {
                const l = c.legs[i], pl = catalog.locations[l.location]
                const before = catalog.locations[c.legs[i - 1].location]
                const dg = pl.gravity !== before.gravity ? `${before.gravity} to ${pl.gravity}` : null
                return (
                  <li key={i}>
                    <button className="prow" onClick={() => setSel(i)}>
                      <span className="grow"><b>{l.label || pl.name}</b>
                        <span className="muted">{l.start > c.today ? `in ${l.start - c.today} days` : 'next'} · {l.days} d{dg ? ` · gravity ${dg}` : ''} · {pl.dose_rate} mSv a day</span></span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </>
        )}
      </section>

      <section className="rise" style={{ ['--d' as string]: 3 }}>
        <div className="section-head">
          <h2>Radiation over the mission</h2>
          <span className="sub">Estimate from the daily dose of each place · NASA career limit {d.limit_msv} mSv</span>
        </div>
        <p className="lead-line">
          So far <b className="num">{d.now_msv} mSv</b>, {Math.round((100 * d.now_msv) / d.limit_msv)}% of the limit.
          By the end of the plan about <b className="num">{Math.round(d.end_msv)} mSv</b>
          {crosses ? <>, past the limit from <b>day {crosses[0]}</b>.</> : '.'}
          {' '}This is the mission dose, the same for everyone; each person's career dose is in My space.
        </p>
        <div className="chart-wide"><LineChart series={[{ pts: d.series, color: 'var(--accent)' }]} refY={d.limit_msv} refLabel={`Career limit ${d.limit_msv} mSv`}
          xLabels={['Launch', `Day ${Math.round(last / 2)}`, `Day ${last}`]} w={1100} h={280} /></div>
      </section>
    </div>
  )
}
