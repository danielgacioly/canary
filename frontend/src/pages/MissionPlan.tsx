// Mission plan: the itinerary mission control registered, read for health. Pick a leg to see
// what the body faces there and what Canary changes. Editing the plan belongs to the admin flow.
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { PlanConditions } from '../api/types'
import Hazards from '../components/Hazards'
import Timeline from '../components/Timeline'
import { LineChart, Loading } from '../components/ui'
import { clockLine } from '../lib/clock'
import { useApi, useSession } from '../state/session'

const BODY: Record<string, string[]> = {
  g0: ['Bone loss at the full 0 g rate, about 1% a month without exercise', 'Fluids shift toward the head: watch the eyes', 'Space sickness is common in the first 72 hours'],
  gp: ['Re-adaptation to weight in the first 30 days after 0 g: dizziness when standing', 'Bone loss slows to about 40% of the 0 g rate', 'Fine, sharp dust outside'],
  g1: ['Bone slowly recovers', 'Baseline training: Canary learns each person\'s normal'],
}
const CANARY: Record<string, string[]> = {
  g0: ['Exercise goal: 2 hours a day, resistance plus treadmill or bike', 'Space-sickness rule active in the first 72 hours of a launch leg', 'Guided Response uses 0 g steps: restraints, tethers, floating fluids'],
  gp: ['Exercise goal: 1 hour of resistance and suited walks', 'Re-adaptation alert in the first 30 days', 'Outside activity follows space weather; partial-gravity steps in Guided Response'],
  g1: ['Training and recovery goals', 'No alerts before launch, only baselines', 'Guided Response uses Earth steps'],
}

export default function MissionPlan() {
  const { mission, catalog } = useSession()
  const { data: c } = useApi<PlanConditions>(() => api.conditions(), [])
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
  const crosses = d.series.find(([, v]) => v >= d.limit_msv)

  return (
    <div className="page">
      <div className="head rise">
        <div>
          <h1>{c.name}</h1>
          <p className="sub">{mission.day_label} · {clockLine(mission.clock)} · {mission.place.name}. Registered by mission control; Canary adapts the crew's health care to every leg.</p>
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
        <div className="stats">
          <div className="stat"><div className="k">Gravity</div><b>{place.gravity}</b></div>
          <div className="stat"><div className="k">Radiation</div><b className="num">{place.dose_rate}<small>mSv/day</small></b></div>
          <div className="stat"><div className="k">Earth replies</div><b>{place.reply}</b></div>
          <div className="stat"><div className="k">Nearest hospital</div><b>{place.hospital}</b></div>
        </div>
        <h3 className="sub-h">Hazards on this leg</h3>
        <Hazards items={leg.ridge} compact />
        <div className="two-lists">
          <div>
            <h3 className="sub-h">What the body faces</h3>
            <ul className="plain">{BODY[leg.gravity_key].map(t => <li key={t}>{t}</li>)}</ul>
          </div>
          <div>
            <h3 className="sub-h">What Canary changes</h3>
            <ul className="plain">
              {CANARY[leg.gravity_key].map(t => <li key={t}>{t}</li>)}
              <li>{place.reply === 'Live' ? 'Messages and reports reach Earth live' : `Messages, briefings and reports wait ${place.reply} each way`}</li>
            </ul>
          </div>
        </div>
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
