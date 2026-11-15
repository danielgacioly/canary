// Dashboard, Blood: one lab value at a time from the real Inspiration4 panels (OSD-569 blood count, OSD-575 metabolic).
import { useState } from 'react'
import type { Analyte, CrewDetail } from '../api/types'
import { domain } from '../lib/scale'
import { useSession } from '../state/session'
import { Plot } from './Trend'

const NAME: Record<string, string> = {
  wbc: 'White cells', lym: 'Lymphocytes', neu: 'Neutrophils', hgb: 'Hemoglobin', hct: 'Hematocrit', plt: 'Platelets', rbc: 'Red cells',
  creatinine: 'Creatinine', potassium: 'Potassium', calcium: 'Calcium', crp: 'C-reactive protein (CRP)',
}
const UNIT: Record<string, string> = {
  thousand_per_microliter: '10³/µL', million_per_microliter: '10⁶/µL', cells_per_microliter: 'cells/µL', grams_per_deciliter: 'g/dL', percent: '%',
}
const PANEL = { cbc: 'Blood count (CBC)', cmp: 'Metabolic panel' } as const
const SOURCE_NAME: Record<string, string> = { 'nasa:osd569': 'OSD-569', 'nasa:osd575': 'OSD-575' }

export default function BloodChart({ d }: { d: CrewDetail }) {
  const { catalog } = useSession()
  const b = d.blood
  const keys = Object.keys(b.analytes)
  const [k, setK] = useState(keys.includes('lym') ? 'lym' : keys[0])
  if (!keys.length) return <p className="small muted">{b.note}</p>
  const a: Analyte = b.analytes[k] ?? b.analytes[keys[0]]
  const unit = UNIT[a.unit] ?? a.unit
  const src = catalog?.sources.find(s => s.id === a.source)
  const pts = a.values.map((v, i) => ({ i, v, out: a.status[i] === 'out' })).filter((p): p is { i: number; v: number; out: boolean } => p.v !== null)
  const dom = domain(pts.map(p => p.v).concat(a.range ? [a.range.min, a.range.max] : []))
  const n = b.timepoints.length
  const num = (v: number) => v.toLocaleString('en-US', { maximumFractionDigits: 2 })
  const outN = pts.filter(p => p.out).length
  return (
    <div className="blood">
      <div className="blood-head">
        <select className="in" value={k} onChange={e => setK(e.target.value)} aria-label="Lab value">
          {(['cbc', 'cmp'] as const).map(panel => (
            <optgroup key={panel} label={PANEL[panel]}>
              {keys.filter(x => b.analytes[x].panel === panel).map(x => <option key={x} value={x}>{NAME[x] ?? x}</option>)}
            </optgroup>
          ))}
        </select>
        <span className="tag">Real NASA data · {src ? <a href={src.url} target="_blank" rel="noreferrer">{SOURCE_NAME[a.source ?? ''] ?? src.name}</a> : SOURCE_NAME[a.source ?? ''] ?? a.source}</span>
      </div>
      <p className="small muted legend">
        <span className="num">{unit}</span>
        {a.range ? <span><i className="key band" />Lab reference {num(a.range.min)} to {num(a.range.max)}</span> : <span>The panel gives no reference range for {k === 'crp' ? 'CRP' : NAME[k] ?? k}</span>}
        {outN > 0 && <span className="out-text"><i className="key out" />{outN} outside the range</span>}
      </p>
      <Plot x={[0, n - 1]} y={dom} h={170} label={`${NAME[k] ?? k} at ${n} blood draws`}
        xTicks={b.timepoints.map((t, i) => ({ x: i, label: t }))}>
        {(X, Y) => (
          <>
            {a.range && <rect x={X(0)} width={X(n - 1) - X(0)} y={Y(a.range.max)} height={Y(a.range.min) - Y(a.range.max)} className="band-fill" />}
            <path d={pts.map((p, j) => `${j ? 'L' : 'M'}${X(p.i).toFixed(1)},${Y(p.v).toFixed(1)}`).join('')} fill="none" stroke="var(--physical)" strokeWidth="1.8" />
            {pts.map(p => <circle key={p.i} cx={X(p.i)} cy={Y(p.v)} r={p.out ? 4 : 3} fill={p.out ? 'var(--watch)' : 'var(--physical)'} />)}
          </>
        )}
      </Plot>
      <p className="small dim">L is days before launch, R days after return. {b.note}</p>
    </div>
  )
}
