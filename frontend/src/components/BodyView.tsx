// The heart of Canary: the body on the left, what it means on the right.
// The right panel shows one thing at a time: the overview, or the system you clicked.
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { CrewDetail, Goal, Indicator } from '../api/types'
import type { CheckKind } from '../features/Checks'
import type { SystemId } from '../hologram/anatomy'
import BodyHologram from '../hologram/BodyHologram'
import type { Lens } from '../hologram/scene'
import { useSession } from '../state/session'
import { GoalRow } from './GoalItems'
import { Icon, Spark, Status } from './ui'

const fmt = (i: Indicator) => i.value.toFixed(i.dp)
const PHYSICAL: SystemId[] = ['heart', 'lungs', 'skeleton', 'muscles', 'eyes', 'kidneys', 'gut', 'immune', 'skin']
const FACETS = ['sleep', 'react', 'mood', 'stress', 'social']

export default function BodyView({ d, onCheck, self = true }: { d: CrewDetail; onCheck?: (k: CheckKind) => void; self?: boolean }) {
  // open on the area that needs attention
  const [lens, setLens] = useState<Lens>(d.areas.mental.level > d.areas.physical.level ? 'mental' : 'physical')
  const [sel, setSel] = useState<SystemId | null>(null)
  const status = useMemo(() => Object.fromEntries(Object.entries(d.systems).map(([k, v]) => [k, v.level])) as Record<SystemId, 0 | 1 | 2>, [d.systems])
  const names = useMemo(() => Object.fromEntries(Object.entries(d.systems).map(([k, v]) => [k, v.name])), [d.systems])
  const choose = (s: SystemId | null) => { setSel(s); if (s) setLens(d.systems[s]?.area === 'mental' ? 'mental' : 'physical') }

  return (
    <div className="today">
      <BodyHologram status={status} lens={lens} selected={sel} onSelect={choose} names={names}>
        <div className="lens" role="tablist" aria-label="Lens">
          {(['physical', 'mental'] as const).map(a => (
            <button key={a} role="tab" aria-selected={lens === a} className={lens === a ? 'on' : ''} onClick={() => { setLens(a); setSel(null) }}>
              <div className="k">{a === 'physical' ? 'Physical' : 'Mental'}</div>
              <div className="v"><b>{d.areas[a].score}</b><Status level={d.areas[a].level} /></div>
            </button>
          ))}
        </div>
        <span className="body-hint">Drag to turn · click any part of the body</span>
      </BodyHologram>

      <aside className="card obs" aria-live="polite">
        {sel
          ? <SystemPanel d={d} sys={sel} onBack={() => choose(null)} onCheck={self ? onCheck : undefined} />
          : <Overview d={d} lens={lens} onPick={choose} onCheck={self ? onCheck : undefined} self={self} />}
      </aside>
    </div>
  )
}

function Overview({ d, lens, onPick, onCheck, self }: { d: CrewDetail; lens: Lens; onPick: (s: SystemId) => void; onCheck?: (k: CheckKind) => void; self: boolean }) {
  const { setEmergency, setAskOpen } = useSession()
  const top = d.alerts[0]
  const first = d.crew.name.split(' ')[0]
  const learning = d.mission.learning
  const headline = learning ? 'Learning your normal.' : top ? top.title : `${self ? 'You are' : `${first} is`} within ${self ? 'your' : 'their'} normal.`
  const why = learning ? 'For 30 days before launch Canary only records how you sleep, react and feel when you are well. Alerts start at launch.'
    : top ? top.why : 'Nothing has left the personal range in the last three days.'
  const rows = lens === 'physical'
    ? PHYSICAL.map(s => ({ id: s, key: s as string, name: d.systems[s].name, level: d.systems[s].level, v: valueOf(d, s) }))
    : FACETS.map(k => ({ id: 'brain' as SystemId, key: k, name: d.indicators[k].facet ?? k, level: d.indicators[k].level, v: `${fmt(d.indicators[k])} ${d.indicators[k].unit}` }))
  const open = d.goals.filter(g => !g.done)
  return (
    <>
      <div className="verdict">
        <span className="eyebrow">{d.crew.name} · {d.mission.day_label}</span>
        <h2>{headline}</h2>
        <p>{why}</p>
      </div>

      {top && (
        <div className="col" style={{ gap: 14 }}>
          <h3>What to do now</h3>
          <ol className="steps">{top.todo.map(t => <li key={t}>{t}</li>)}</ol>
          <div className="row wrap">
            {top.test && onCheck && <button className="btn pri" onClick={() => onCheck(top.test as CheckKind)}>Take the reaction test</button>}
            {top.protocol && <button className="btn pri" onClick={() => setEmergency(true)}>Open the radiation protocol</button>}
            {top.sys && <button className="btn" onClick={() => onPick(top.sys as SystemId)}>See on the body</button>}
            {self && <button className="btn ghost" onClick={() => setAskOpen(true)}><Icon name="ask" />Ask why</button>}
          </div>
        </div>
      )}

      <div className="col" style={{ gap: 4 }}>
        <div className="row"><h3>{lens === 'physical' ? 'Body systems' : 'Mind'}</h3><span className="small dim right">sorted by attention</span></div>
        <div className="list">
          {[...rows].sort((a, b) => b.level - a.level).map(r => (
            <button key={r.key}className={`item s${r.level}`} onClick={() => onPick(r.id)}>
              <span className="dot" /><span>{r.name}</span><span className="v">{r.v}</span><span className="chev"><Icon name="chev" size={14} /></span>
            </button>
          ))}
        </div>
      </div>

      {self && !!open.length && (
        <div className="col" style={{ gap: 4 }}>
          <div className="row"><h3>Next goals</h3><Link to="/goals" className="link right">All goals</Link></div>
          <div>{open.slice(0, 3).map((g: Goal) => <GoalRow key={g.id} g={g} crewId={d.crew.id} onCheck={onCheck} compact />)}</div>
        </div>
      )}
    </>
  )
}

function valueOf(d: CrewDetail, s: SystemId) {
  const st = d.systems[s]
  if (s === 'skin') return `${d.dose.mission_msv} mSv`
  if (!st.indicators.length) return st.status
  const i = d.indicators[st.indicators[0]]
  return `${fmt(i)} ${i.unit}`
}

function SystemPanel({ d, sys, onBack, onCheck }: { d: CrewDetail; sys: SystemId; onBack: () => void; onCheck?: (k: CheckKind) => void }) {
  const st = d.systems[sys], info = d.system_info[sys]
  const alert = d.alerts.find(a => a.sys === sys)
  const goals = d.goals.filter(g => g.sys === sys)
  const col = st.area === 'mental' ? 'var(--mental)' : 'var(--physical)'
  const action: Record<string, [CheckKind, string]> = { eyes: ['amsler', 'Do the Amsler grid'], heart: ['vitals', 'Enter vital signs'], brain: ['pvt', 'Take the reaction test'] }
  return (
    <>
      <button className="back" onClick={onBack}><Icon name="back" />All observations</button>
      <div className="verdict">
        <span className="eyebrow">{st.area} · {info.hazard}</span>
        <h2>{st.name}</h2>
        <div style={{ marginTop: 8 }}><Status level={st.level} /></div>
        {st.note && <p>{st.note}</p>}
      </div>

      {alert && (
        <div className="col" style={{ gap: 12 }}>
          <h3>{alert.title}</h3>
          <p className="muted">{alert.why}</p>
          <ol className="steps">{alert.todo.map(t => <li key={t}>{t}</li>)}</ol>
        </div>
      )}

      {(!!st.indicators.length || sys === 'skin' || sys === 'immune') && (
        <div>
          {st.indicators.map(k => {
            const i = d.indicators[k]
            return (
              <div key={k} className="metric">
                <div><div className="lbl">{i.name}</div><div className="big">{fmt(i)}<small>{i.unit}</small></div><div className="small dim">your normal {i.baseline.toFixed(i.dp)} · <span className={`s${i.level} c`}>{['on track', 'watch', 'act'][i.level]}</span></div></div>
                <Spark data={d.trends[k]} base={i.baseline} color={col} w={130} h={44} />
              </div>
            )
          })}
          {sys === 'skin' && (
            <div className="metric"><div><div className="lbl">Mission dose (simulated)</div><div className="big">{d.dose.mission_msv}<small>mSv</small></div><div className="small dim">{d.dose.pct_of_limit}% of the {d.dose.career_limit_msv} mSv career limit</div></div></div>
          )}
          {sys === 'immune' && <Blood d={d} />}
        </div>
      )}

      <div className="col" style={{ gap: 6 }}>
        <h3>What space does here</h3>
        <p className="muted">{info.space}</p>
      </div>

      {(onCheck && action[sys]) && <button className="btn pri" style={{ alignSelf: 'flex-start' }} onClick={() => onCheck(action[sys][0])}>{action[sys][1]}</button>}
      {onCheck && sys === 'brain' && <button className="btn" style={{ alignSelf: 'flex-start' }} onClick={() => onCheck('mood')}>Mood check-in</button>}

      {!!goals.length && (
        <div className="col" style={{ gap: 4 }}>
          <h3>Goals for this</h3>
          <div>{goals.slice(0, 4).map(g => <GoalRow key={g.id} g={g} crewId={d.crew.id} onCheck={onCheck} compact readOnly={!onCheck} />)}</div>
        </div>
      )}
    </>
  )
}

function Blood({ d }: { d: CrewDetail }) {
  const b = d.blood, w = 340, h = 120
  const lo = Math.min(b.range.min, ...b.lymphocytes) * 0.9, hi = Math.max(b.range.max, ...b.lymphocytes) * 1.05
  const X = (i: number) => 14 + (i / (b.lymphocytes.length - 1)) * (w - 28), Y = (v: number) => h - 20 - ((v - lo) / (hi - lo)) * (h - 30)
  return (
    <div className="metric" style={{ display: 'block' }}>
      <div className="lbl">Lymphocytes · real NASA data (OSD-569, Inspiration4)</div>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" className="chart" style={{ marginTop: 8 }}>
        <rect x="14" width={w - 28} y={Y(b.range.max)} height={Y(b.range.min) - Y(b.range.max)} fill="var(--surface-2)" />
        <path d={b.lymphocytes.map((v, i) => `${i ? 'L' : 'M'}${X(i)},${Y(v)}`).join('')} fill="none" stroke="var(--physical)" strokeWidth="1.8" />
        {b.lymphocytes.map((v, i) => <circle key={i} cx={X(i)} cy={Y(v)} r="2.5" fill="var(--physical)" />)}
        {b.timepoints.map((t, i) => <text key={t} x={X(i)} y={h - 4} textAnchor="middle">{t}</text>)}
      </svg>
      <div className="small dim">Shaded band: reference range. Shown as a reference curve for this crew member.</div>
    </div>
  )
}
