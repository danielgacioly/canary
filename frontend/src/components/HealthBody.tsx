// Physical | hologram | mental. Click any part of the body (or a row) to open that system.
import { useMemo, useState } from 'react'
import type { CrewDetail, Indicator } from '../api/types'
import type { SystemId } from '../hologram/anatomy'
import BodyHologram from '../hologram/BodyHologram'
import type { Lens } from '../hologram/scene'
import { Gauge, Icon, Pill, Spark, STATUS } from './ui'

const fmt = (i: Indicator) => i.value.toFixed(i.dp)
const PHYS_ORDER: SystemId[] = ['heart', 'lungs', 'skeleton', 'muscles', 'eyes', 'kidneys', 'gut', 'immune', 'skin']
const FACETS = ['sleep', 'react', 'mood', 'stress', 'social']

export default function HealthBody({ d, onCheck }: { d: CrewDetail; onCheck?: (k: 'pvt' | 'mood' | 'amsler' | 'vitals') => void }) {
  const [lens, setLens] = useState<Lens>('physical')
  const [sel, setSel] = useState<SystemId | null>(null)
  const status = useMemo(() => Object.fromEntries(Object.entries(d.systems).map(([k, v]) => [k, v.level])) as Record<SystemId, 0 | 1 | 2>, [d.systems])
  const names = useMemo(() => Object.fromEntries(Object.entries(d.systems).map(([k, v]) => [k, v.name])), [d.systems])
  const mentalGoals = d.goals.filter(g => g.area === 'mental'), physGoals = d.goals.filter(g => g.area === 'physical')
  const choose = (s: SystemId | null) => { setSel(s); if (s) setLens(d.systems[s]?.area === 'mental' ? 'mental' : 'physical') }

  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="bodyview">
        {/* PHYSICAL */}
        <section className="card side-panel phys-side" aria-label="Physical health">
          <div className="area-head">
            <Gauge value={d.areas.physical.score} color="var(--physical)" size={96} />
            <div className="col" style={{ gap: 6 }}>
              <span className="lbl" style={{ color: 'var(--physical)' }}>Physical</span>
              <Pill level={d.areas.physical.level} />
              <span className="small muted">{physGoals.filter(g => g.done).length}/{physGoals.length} goals today</span>
            </div>
          </div>
          <div className="hr" />
          <div className="col" style={{ gap: 2 }}>
            {PHYS_ORDER.map(s => {
              const st = d.systems[s]; const first = st.indicators[0] ? d.indicators[st.indicators[0]] : null
              return (
                <button key={s} className={`sysrow s${st.level} ${sel === s ? 'on' : ''}`} onClick={() => choose(sel === s ? null : s)}>
                  <span className="dot" /><span>{st.name}</span>
                  <span className="v">{first ? `${fmt(first)} ${first.unit}` : s === 'skin' ? `${d.dose.mission_msv} mSv` : st.status}</span>
                </button>
              )
            })}
          </div>
        </section>

        {/* HOLOGRAM */}
        <div className="holo-col">
          <BodyHologram status={status} lens={lens} selected={sel} onSelect={choose} names={names} levels={status}>
            <div className="holo-top">
              <div className="seg" role="tablist" aria-label="Lens">
                <button className={`phys ${lens === 'physical' ? 'on' : ''}`} onClick={() => setLens('physical')}>Physical</button>
                <button className={`ment ${lens === 'mental' ? 'on' : ''}`} onClick={() => setLens('mental')}>Mental</button>
              </div>
            </div>
            <div className="holo-foot">
              <span className="lbl">{sel ? names[sel] : 'Drag to turn · click a part of the body'}</span>
              {sel && <button className="btn sm right" style={{ pointerEvents: 'auto' }} onClick={() => choose(null)}>Whole body</button>}
            </div>
          </BodyHologram>
        </div>

        {/* MENTAL */}
        <section className="card side-panel ment-side" aria-label="Mental health">
          <div className="area-head">
            <Gauge value={d.areas.mental.score} color="var(--mental)" size={96} />
            <div className="col" style={{ gap: 6 }}>
              <span className="lbl" style={{ color: 'var(--mental)' }}>Mental</span>
              <Pill level={d.areas.mental.level} />
              <span className="small muted">{mentalGoals.filter(g => g.done).length}/{mentalGoals.length} goals today</span>
            </div>
          </div>
          <div className="hr" />
          <div className="col" style={{ gap: 2 }}>
            {FACETS.map(k => {
              const i = d.indicators[k]
              return (
                <button key={k} className={`sysrow s${i.level}`} onClick={() => choose('brain')}>
                  <span className="dot" /><span className="col" style={{ gap: 0 }}><span>{i.facet}</span><span className="small dim">{i.name}</span></span>
                  <span className="right"><Spark data={d.trends[k].slice(-14)} base={i.baseline} color="var(--mental)" w={70} h={24} /></span>
                  <span className="v" style={{ marginLeft: 8, minWidth: 54, textAlign: 'right' }}>{fmt(i)} {i.unit}</span>
                </button>
              )
            })}
          </div>
          <div className="hr" />
          <span className="lbl">Mind goals today</span>
          <div className="row wrap" style={{ gap: 6 }}>
            {mentalGoals.slice(0, 8).map(g => <span key={g.id} className={`tag ${g.done ? 'ment' : ''}`} title={g.title}>{g.done ? '✓ ' : ''}{short(g.id, g.title)}</span>)}
          </div>
        </section>
      </div>

      {sel && <SystemDetail d={d} sys={sel} onClose={() => choose(null)} onCheck={onCheck} />}
    </div>
  )
}

function short(id: string, title: string) {
  return ({ sleep: 'Sleep 7 h', pvt: 'Reaction test', mood: 'Check-in', meditate: 'Meditation', read: 'Reading', social: 'Crew time', leisure: 'Film or music', home: 'Call home', window: 'Look homeward', journal: 'Journal' } as Record<string, string>)[id] ?? title
}

function SystemDetail({ d, sys, onClose, onCheck }: { d: CrewDetail; sys: SystemId; onClose: () => void; onCheck?: (k: 'pvt' | 'mood' | 'amsler' | 'vitals') => void }) {
  const st = d.systems[sys], info = d.system_info[sys]
  const alerts = d.alerts.filter(a => a.sys === sys)
  const goals = d.goals.filter(g => g.sys === sys || (sys === 'brain' && g.area === 'mental' && g.by !== 'routine'))
  const col = st.area === 'mental' ? 'var(--mental)' : 'var(--physical)'
  return (
    <section className={`card detail glow s${st.level}`}>
      <div className="head">
        <div><span className="lbl" style={{ color: col }}>{st.area} · {info.hazard}</span><h2 style={{ marginTop: 4 }}>{st.name}</h2></div>
        <Pill level={st.level} />
        <button className="btn sm ghost right" onClick={onClose}><Icon name="close" size={15} /></button>
      </div>
      <div className="grid" style={{ gridTemplateColumns: 'minmax(0,1.3fr) minmax(0,1fr)', gap: 18 }}>
        <div className="col" style={{ gap: 12 }}>
          {!!st.indicators.length && (
            <div className="grid g2">
              {st.indicators.map(k => {
                const i = d.indicators[k]
                return (
                  <div key={k} className={`metric s${i.level}`}>
                    <span className="lbl">{i.name}</span><span className="pill" style={{ justifySelf: 'end' }}><span className="dot" />{STATUS[i.level]}</span>
                    <span className="big">{fmt(i)}<small>{i.unit}</small></span>
                    <span className="small muted" style={{ alignSelf: 'end' }}>normal {i.baseline.toFixed(i.dp)}</span>
                    <div style={{ gridColumn: '1 / -1', marginTop: 6 }}><Spark data={d.trends[k]} base={i.baseline} color={col} w={300} h={44} /></div>
                  </div>
                )
              })}
            </div>
          )}
          {sys === 'immune' && <BloodChart d={d} />}
          {sys === 'skin' && (
            <div className="metric"><span className="lbl">Mission dose (simulated)</span><span />
              <span className="big">{d.dose.mission_msv}<small>mSv</small></span><span className="small muted">{d.dose.pct_of_limit}% of {d.dose.career_limit_msv} mSv career limit</span>
              <div className="prog" style={{ gridColumn: '1 / -1', marginTop: 8, ['--pc' as string]: 'var(--gold)' }}><i style={{ width: `${Math.min(100, d.dose.pct_of_limit)}%` }} /></div></div>
          )}
          {st.note && <p className="small" style={{ color: 'var(--c)' }}>{st.note}</p>}
          {sys === 'eyes' && onCheck && <button className="btn" style={{ alignSelf: 'flex-start' }} onClick={() => onCheck('amsler')}>Do the Amsler grid now</button>}
          {sys === 'heart' && onCheck && <button className="btn" style={{ alignSelf: 'flex-start' }} onClick={() => onCheck('vitals')}>Enter vital signs</button>}
          {sys === 'brain' && onCheck && <div className="row"><button className="btn" onClick={() => onCheck('pvt')}>Reaction test</button><button className="btn" onClick={() => onCheck('mood')}>Mood check-in</button></div>}
        </div>
        <div className="col" style={{ gap: 12 }}>
          <div><span className="lbl">What space does here</span><p style={{ marginTop: 6 }}>{info.space}</p></div>
          {alerts.map(a => (
            <div key={a.id} className={`card flat alert tight s${a.level}`}><b>{a.title}</b><p className="small muted" style={{ marginTop: 4 }}>{a.why}</p>
              <ol className="todo">{a.todo.map(t => <li key={t}>{t}</li>)}</ol></div>
          ))}
          {!!goals.length && <div><span className="lbl">Linked goals</span>
            <div className="col" style={{ gap: 6, marginTop: 8 }}>{goals.slice(0, 5).map(g => <span key={g.id} className="small">{g.done ? '✓' : '○'} {g.title} <span className="xp">+{g.xp} XP</span></span>)}</div></div>}
        </div>
      </div>
    </section>
  )
}

function BloodChart({ d }: { d: CrewDetail }) {
  const b = d.blood, w = 300, h = 110, lo = Math.min(b.range.min, ...b.lymphocytes) * 0.9, hi = Math.max(b.range.max, ...b.lymphocytes) * 1.05
  const X = (i: number) => 10 + (i / (b.lymphocytes.length - 1)) * (w - 20), Y = (v: number) => h - 18 - ((v - lo) / (hi - lo)) * (h - 28)
  return (
    <div className="metric">
      <span className="lbl">Lymphocytes · NASA OSD-569</span><span className="tag">real data</span>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ gridColumn: '1 / -1', marginTop: 6 }} className="chart">
        <rect x="10" width={w - 20} y={Y(b.range.max)} height={Y(b.range.min) - Y(b.range.max)} fill="rgba(61,220,151,.07)" />
        <path d={b.lymphocytes.map((v, i) => `${i ? 'L' : 'M'}${X(i)},${Y(v)}`).join('')} fill="none" stroke="#9dff9a" strokeWidth="1.8" />
        {b.lymphocytes.map((v, i) => <circle key={i} cx={X(i)} cy={Y(v)} r="2.6" fill="#9dff9a" />)}
        {b.timepoints.map((t, i) => <text key={t} x={X(i)} y={h - 4} textAnchor="middle">{t}</text>)}
      </svg>
      <span className="small muted" style={{ gridColumn: '1 / -1' }}>{b.note} Green band: reference range.</span>
    </div>
  )
}
