// Today, as a dashboard: the body and the verdict first, then the physical and mental
// systems as tiles, then goals and the mission leg. Click any part of the body or any tile
// and the verdict area becomes that system.
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { CrewDetail, Indicator } from '../api/types'
import type { CheckKind } from '../features/Checks'
import type { SystemId } from '../hologram/anatomy'
import BodyHologram from '../hologram/BodyHologram'
import type { Lens } from '../hologram/scene'
import { useSession } from '../state/session'
import { GoalRow } from './GoalItems'
import { CountUp, Icon, Spark, Status } from './ui'

const fmt = (i: Indicator) => i.value.toFixed(i.dp)
const PHYSICAL: SystemId[] = ['heart', 'lungs', 'skeleton', 'muscles', 'eyes', 'kidneys', 'gut', 'immune', 'skin']
const FACETS = ['sleep', 'react', 'mood', 'stress', 'social']

export default function BodyView({ d, onCheck, self = true }: { d: CrewDetail; onCheck?: (k: CheckKind) => void; self?: boolean }) {
  const [lens, setLens] = useState<Lens>(d.areas.mental.level > d.areas.physical.level ? 'mental' : 'physical')
  const [sel, setSel] = useState<SystemId | null>(null)
  const status = useMemo(() => Object.fromEntries(Object.entries(d.systems).map(([k, v]) => [k, v.level])) as Record<SystemId, 0 | 1 | 2>, [d.systems])
  const names = useMemo(() => Object.fromEntries(Object.entries(d.systems).map(([k, v]) => [k, v.name])), [d.systems])
  const choose = (s: SystemId | null, scroll = false) => {
    setSel(s)
    if (s) setLens(d.systems[s]?.area === 'mental' ? 'mental' : 'physical')
    if (scroll) window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  const physical = [...PHYSICAL].sort((a, b) => d.systems[b].level - d.systems[a].level)
  const mental = [...FACETS].sort((a, b) => d.indicators[b].level - d.indicators[a].level)

  return (
    <>
      <section className="hero">
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
              <button key={a} className={`area ${lens === a ? 'on' : ''}`} onClick={() => { setLens(a); setSel(null); document.getElementById(`sec-${a}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }}>
                <div className="k">{a === 'physical' ? 'Physical' : 'Mental'}</div>
                <b className="num"><CountUp value={d.areas[a].score} /></b>
                <Status level={d.areas[a].level} />
              </button>
            ))}
          </div>
        </div>
      </section>

      <section id="sec-physical">
        <div className="section-head rise"><h2>Physical</h2><span className="sub">{d.areas.physical.score} · sorted by what needs attention</span></div>
        <div className="tiles">
          {physical.map((s, i) => {
            const st = d.systems[s]; const ind = st.indicators[0] ? d.indicators[st.indicators[0]] : null
            return (
              <button key={s} className={`tile rise s${st.level} ${sel === s ? 'on' : ''}`} style={{ ['--d' as string]: i }} onClick={() => choose(s, true)}>
                <div className="top"><span className="dot" />{st.name}</div>
                <div className="foot">
                  <div><div className="tv">{ind ? fmt(ind) : s === 'skin' ? d.dose.mission_msv : st.status}<small>{ind ? ind.unit : s === 'skin' ? 'mSv' : ''}</small></div>
                    <div className="small dim" style={{ marginTop: 6 }}>{ind ? `normal ${ind.baseline.toFixed(ind.dp)}` : s === 'skin' ? `${d.dose.pct_of_limit}% of career limit` : st.note ?? 'Self-check'}</div></div>
                  {ind && <Spark data={d.trends[ind.id].slice(-14)} base={ind.baseline} color="var(--physical)" w={70} h={28} />}
                </div>
              </button>
            )
          })}
        </div>
      </section>

      <section id="sec-mental">
        <div className="section-head rise"><h2>Mental</h2><span className="sub">{d.areas.mental.score} · rest, focus, mood, stress, connection</span></div>
        <div className="tiles">
          {mental.map((k, i) => {
            const ind = d.indicators[k]
            return (
              <button key={k} className={`tile rise s${ind.level}`} style={{ ['--d' as string]: i }} onClick={() => choose('brain', true)}>
                <div className="top"><span className="dot" />{ind.facet}<span className="small dim right">{ind.name}</span></div>
                <div className="foot">
                  <div><div className="tv">{fmt(ind)}<small>{ind.unit}</small></div><div className="small dim" style={{ marginTop: 6 }}>normal {ind.baseline.toFixed(ind.dp)}</div></div>
                  <Spark data={d.trends[k].slice(-14)} base={ind.baseline} color="var(--mental)" w={70} h={28} />
                </div>
              </button>
            )
          })}
        </div>
      </section>

      {self && <TodayBottom d={d} onCheck={onCheck} />}
    </>
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
  return (
    <>
      <div>
        <h1 className="rise">{headline}</h1>
        <p className="why rise">{why}</p>
        <p className="meta rise">{self ? `Hello, ${first}` : d.crew.name} · {d.mission.day_label} · {d.mission.place.name}</p>
      </div>
      {top && (
        <div className="col rise" style={{ gap: 14, ['--d' as string]: 3 }}>
          <h3>What to do now</h3>
          <ol className="steps">{top.todo.map(t => <li key={t}>{t}</li>)}</ol>
          <div className="row wrap">
            {top.test && onCheck && self && <button className="btn pri" onClick={() => onCheck(top.test as CheckKind)}>Take the reaction test</button>}
            {top.protocol && <button className="btn pri" onClick={() => setEmergency(true)}>Open the radiation protocol</button>}
            {top.sys && <button className="btn" onClick={() => onPick(top.sys as SystemId)}>Show on the body</button>}
            {self && <button className="btn ghost" onClick={() => setAskOpen(true)}><Icon name="ask" />Ask why</button>}
          </div>
          {d.alerts.length > 1 && <span className="small dim">{d.alerts.length - 1} more {d.alerts.length > 2 ? 'observations' : 'observation'} below, marked in colour.</span>}
        </div>
      )}
    </>
  )
}

function SystemPanel({ d, sys, onBack, onCheck }: { d: CrewDetail; sys: SystemId; onBack: () => void; onCheck?: (k: CheckKind) => void }) {
  const st = d.systems[sys], info = d.system_info[sys]
  const alert = d.alerts.find(a => a.sys === sys)
  const col = st.area === 'mental' ? 'var(--mental)' : 'var(--physical)'
  const action: Record<string, [CheckKind, string]> = { eyes: ['amsler', 'Do the Amsler grid'], heart: ['vitals', 'Enter vital signs'], brain: ['pvt', 'Take the reaction test'] }
  return (
    <div className="col" style={{ gap: 20 }}>
      <button className="back rise" onClick={onBack}><Icon name="back" />Back to today</button>
      <div className="rise" style={{ ['--d' as string]: 1 }}>
        <h1>{st.name}</h1>
        <p className="meta" style={{ textTransform: 'capitalize' }}>{st.area} · {info.hazard}</p>
        <div style={{ marginTop: 10 }}><Status level={st.level} /></div>
        {st.note && <p className="why">{st.note}</p>}
      </div>
      {alert && (
        <div className="col rise" style={{ gap: 10, ['--d' as string]: 2 }}>
          <h3>{alert.title}</h3>
          <ol className="steps">{alert.todo.map(t => <li key={t}>{t}</li>)}</ol>
        </div>
      )}
      {!!st.indicators.length && (
        <div className="rise" style={{ ['--d' as string]: 3 }}>
          {st.indicators.map(k => {
            const i = d.indicators[k]
            return (
              <div key={k} className="metric">
                <div><div className="lbl">{i.name}</div><div className="big">{fmt(i)}<small>{i.unit}</small></div><div className="small dim">normal {i.baseline.toFixed(i.dp)} · <span className={`s${i.level} c`}>{['on track', 'watch', 'act'][i.level]}</span></div></div>
                <Spark data={d.trends[k]} base={i.baseline} color={col} w={150} h={44} />
              </div>
            )
          })}
        </div>
      )}
      {sys === 'immune' && <Blood d={d} />}
      <p className="muted rise" style={{ ['--d' as string]: 4 }}>{info.space}</p>
      {onCheck && (action[sys] || sys === 'brain') && (
        <div className="row wrap rise" style={{ ['--d' as string]: 5 }}>
          {action[sys] && <button className="btn pri" onClick={() => onCheck(action[sys][0])}>{action[sys][1]}</button>}
          {sys === 'brain' && <button className="btn" onClick={() => onCheck('mood')}>Mood check-in</button>}
        </div>
      )}
    </div>
  )
}

function TodayBottom({ d, onCheck }: { d: CrewDetail; onCheck?: (k: CheckKind) => void }) {
  const open = d.goals.filter(g => !g.done)
  const done = d.goals.length - open.length
  const leg = d.mission.leg
  return (
    <section className="grid g2">
      <div className="detail-card rise">
        <div className="section-head"><h2>Today's goals</h2><span className="sub">{done} of {d.goals.length} done</span><Link to="/goals" className="link right">All goals</Link></div>
        <div className="bar-track" style={{ marginBottom: 10, ['--pc' as string]: 'var(--ok)' }}><i style={{ width: `${(100 * done) / d.goals.length}%` }} /></div>
        {open.slice(0, 4).map(g => <GoalRow key={g.id} g={g} crewId={d.crew.id} onCheck={onCheck} compact />)}
        {!open.length && <p className="muted">Everything done. Rest is a goal too.</p>}
      </div>
      <div className={`detail-card rise p-${d.mission.location}`}>
        <div className="section-head"><span className="pc-dot" /><h2>{d.mission.place.name}</h2><span className="sub">{leg.label}</span><Link to="/plan" className="link right">Mission plan</Link></div>
        <dl className="adapt">
          <dt>This leg</dt><dd>Day {leg.day_in_leg} of {leg.length}</dd>
          <dt>Next</dt><dd>{leg.next ? `${leg.next.label || leg.next.location} in ${leg.days_to_next} days` : 'End of plan'}</dd>
          <dt>Gravity</dt><dd>{d.mission.place.gravity}</dd>
          <dt>Earth replies</dt><dd>{d.mission.place.reply}</dd>
          <dt>Radiation</dt><dd>{d.mission.place.dose_rate} mSv/day · mission total {d.dose.mission_msv} mSv</dd>
          <dt>Hospital</dt><dd>{d.mission.place.hospital}</dd>
        </dl>
        <p className="small muted" style={{ marginTop: 14 }}>{d.mission.place.what}</p>
      </div>
    </section>
  )
}

function Blood({ d }: { d: CrewDetail }) {
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
