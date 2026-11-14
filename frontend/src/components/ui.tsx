// Small building blocks shared by every screen: icons, status pills, gauges, charts and mission patches.
import { useEffect, useState, type ReactNode } from 'react'
import type { Level } from '../api/types'

export const STATUS = ['On track', 'Watch', 'Act'] as const

const paths: Record<string, string> = {
  me: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 9a7 7 0 0 1 14 0',
  crew: 'M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm-6 9a6 6 0 0 1 12 0m1.5-9a3 3 0 1 0 0-6m2.5 15a5 5 0 0 0-3-4.6',
  goals: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-4a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm0-4a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z',
  rank: 'M7 21V11m5 10V5m5 16v-7',
  mission: 'M12 3c3 2 5 6 5 10l-2 3H9l-2-3c0-4 2-8 5-10Zm-3 13-2 4m10-4 2 4M12 10.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z',
  med: 'M10 3h4v7h7v4h-7v7h-4v-7H3v-4h7V3Z',
  info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-11v6m0-9v.01',
  ask: 'M4 5h16v11H9l-5 4V5Zm4 5h.01M12 10h.01M16 10h.01',
  check: 'm5 12 4.5 4.5L19 7',
  close: 'M6 6l12 12M18 6 6 18',
  chev: 'm9 6 6 6-6 6',
  back: 'm15 6-6 6 6 6',
  globe: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-9-9h18M12 3c2.5 2.5 3.5 5.5 3.5 9s-1 6.5-3.5 9c-2.5-2.5-3.5-5.5-3.5-9s1-6.5 3.5-9Z',
  send: 'm4 12 16-8-6 16-2.5-6.5L4 12Z',
  bolt: 'M13 3 5 14h6l-1 7 8-11h-6l1-7Z',
  spark: 'M12 3v4m0 10v4M3 12h4m10 0h4M6 6l2.5 2.5m7 7L18 18M18 6l-2.5 2.5m-7 7L6 18',
}
export function Icon({ name, size = 17 }: { name: keyof typeof paths | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[name] ?? paths.info} />
    </svg>
  )
}

export function CanaryMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <defs><linearGradient id="cm" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#ffd86b" /><stop offset="1" stopColor="#ffb02e" /></linearGradient></defs>
      <path d="M3 9l5 3-1 4c0 6 5 11 12 11 5 0 8-3 8-7 0-3-2-5-4-6-1-1-1-3-3-4-3-2-6-1-8 1L3 9z" fill="url(#cm)" />
      <circle cx="12" cy="13" r="1.4" fill="#04060b" />
    </svg>
  )
}

export function Pill({ level, children }: { level: Level | number; children?: ReactNode }) {
  return <span className={`pill s${level}`}><span className="dot" />{children ?? STATUS[level]}</span>
}

/** Count up to a number once, for the "alive" feel without decoration. */
export function CountUp({ value, dp = 0, ms = 900 }: { value: number; dp?: number; ms?: number }) {
  const [v, setV] = useState(0)
  useEffect(() => {
    let raf = 0
    const t0 = performance.now(), from = 0
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3)
      setV(from + (value - from) * e)
      if (k < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [value, ms])
  return <>{v.toFixed(dp)}</>
}

/** Circular gauge for a 0-100 score. */
export function Gauge({ value, color, size = 120, label, sub }: { value: number; color: string; size?: number; label?: string; sub?: string }) {
  const r = size / 2 - 9, c = 2 * Math.PI * r
  const [k, setK] = useState(0)
  useEffect(() => { const t = setTimeout(() => setK(value / 100), 60); return () => clearTimeout(t) }, [value])
  return (
    <div style={{ position: 'relative', width: size, height: size, flex: 'none' }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(150,178,230,.12)" strokeWidth="5" />
        {Array.from({ length: 40 }).map((_, i) => {
          const a = (i / 40) * Math.PI * 2, x1 = size / 2 + Math.cos(a) * (r + 6), y1 = size / 2 + Math.sin(a) * (r + 6)
          const x2 = size / 2 + Math.cos(a) * (r + 8), y2 = size / 2 + Math.sin(a) * (r + 8)
          return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(150,178,230,.22)" strokeWidth="1" />
        })}
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="5" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - k)} style={{ transition: 'stroke-dashoffset 1.3s cubic-bezier(.2,.7,.2,1)', filter: `drop-shadow(0 0 6px ${color})` }} />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'grid', placeContent: 'center', textAlign: 'center' }}>
        <b style={{ font: `600 ${size / 3.6}px/1 var(--f-display)`, fontStretch: '110%' }}><CountUp value={value} /></b>
        {label && <span className="lbl" style={{ marginTop: 4 }}>{label}</span>}
        {sub && <span className="small muted">{sub}</span>}
      </div>
    </div>
  )
}

/** Sparkline with the personal baseline as a dashed line. */
export function Spark({ data, base, color = 'var(--cyan)', w = 140, h = 36 }: { data: [number, number][]; base?: number; color?: string; w?: number; h?: number }) {
  if (!data.length) return null
  const ys = data.map(d => d[1]).concat(base ?? [])
  const lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1
  const X = (i: number) => (i / (data.length - 1)) * w, Y = (v: number) => h - 3 - ((v - lo) / span) * (h - 6)
  const line = data.map((d, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(d[1]).toFixed(1)}`).join('')
  const id = `sg${Math.round(Math.random() * 1e6)}`
  return (
    <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ ['--sc' as string]: color }}>
      <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={color} stopOpacity=".35" /><stop offset="1" stopColor={color} stopOpacity="0" /></linearGradient></defs>
      <path d={`${line}L${w},${h}L0,${h}Z`} fill={`url(#${id})`} />
      {base !== undefined && <line x1="0" x2={w} y1={Y(base)} y2={Y(base)} stroke="rgba(233,238,248,.35)" strokeDasharray="3 3" />}
      <path className="l" d={line} />
      <circle cx={X(data.length - 1)} cy={Y(data[data.length - 1][1])} r="2.6" fill={color} />
    </svg>
  )
}

/** Generic line chart for NASA series. */
export function LineChart({ series, w = 560, h = 180, yLabel, xLabels, refY, refLabel, band }:
  { series: { pts: [number, number][]; color: string; label?: string }[]; w?: number; h?: number; yLabel?: string; xLabels?: string[]; refY?: number; refLabel?: string; band?: [number, number] }) {
  const all = series.flatMap(s => s.pts)
  const xs = all.map(p => p[0]), ys = all.map(p => p[1]).concat(refY ?? [], band ?? [])
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(0, ...ys), y1 = Math.max(...ys) * 1.08
  const P = { l: 46, r: 12, t: 12, b: 24 }
  const X = (x: number) => P.l + ((x - x0) / (x1 - x0 || 1)) * (w - P.l - P.r)
  const Y = (y: number) => h - P.b - ((y - y0) / (y1 - y0 || 1)) * (h - P.t - P.b)
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(k => y0 + k * (y1 - y0))
  return (
    <svg className="chart" viewBox={`0 0 ${w} ${h}`} width="100%" role="img" aria-label={yLabel}>
      {ticks.map((t, i) => <g key={i}><line className="gl" x1={P.l} x2={w - P.r} y1={Y(t)} y2={Y(t)} /><text x={P.l - 6} y={Y(t) + 3} textAnchor="end">{t >= 1000 ? `${(t / 1000).toFixed(1)}k` : t.toFixed(t < 10 ? 1 : 0)}</text></g>)}
      {band && <rect x={P.l} width={w - P.l - P.r} y={Y(band[1])} height={Y(band[0]) - Y(band[1])} fill="rgba(61,220,151,.07)" />}
      {refY !== undefined && <><line x1={P.l} x2={w - P.r} y1={Y(refY)} y2={Y(refY)} stroke="rgba(233,238,248,.4)" strokeDasharray="4 4" /><text x={w - P.r} y={Y(refY) - 5} textAnchor="end">{refLabel}</text></>}
      {series.map((s, i) => (
        <path key={i} d={s.pts.map((p, j) => `${j ? 'L' : 'M'}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('')} fill="none" stroke={s.color} strokeWidth="1.8" style={{ filter: `drop-shadow(0 0 4px ${s.color})` }} />
      ))}
      {xLabels?.map((l, i) => <text key={i} x={P.l + (i / (xLabels.length - 1)) * (w - P.l - P.r)} y={h - 6} textAnchor={i === 0 ? 'start' : i === xLabels.length - 1 ? 'end' : 'middle'}>{l}</text>)}
    </svg>
  )
}

/** Mission patch: hexagonal, engraved line art. Earned patches glow in their area colour. */
export function Patch({ id, earned, area }: { id: string; earned: boolean; area: string }) {
  const col = area === 'physical' ? '#5ef2ff' : area === 'mental' ? '#b28bff' : '#ffcf5c'
  const glyph: Record<string, string> = {
    iron_bones: 'M20 36l16-16m-14 2a3 3 0 1 1-4-4 3 3 0 1 1 4 4Zm16 16a3 3 0 1 1 4-4 3 3 0 1 1-4 4Z',
    hydro: 'M29 18s-8 9-8 15a8 8 0 0 0 16 0c0-6-8-15-8-15Z',
    still_water: 'M18 34c4-3 7-3 11 0s7 3 11 0M18 28c4-3 7-3 11 0s7 3 11 0',
    deep_reader: 'M29 22c-4-2-8-2-11-1v17c3-1 7-1 11 1 4-2 8-2 11-1V21c-3-1-7-1-11 1Zm0 0v17',
    crew_glue: 'M24 30a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm10 0a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM17 40a7 7 0 0 1 14 0m-3 0a7 7 0 0 1 14 0',
    honest_signal: 'M18 29h6l3-8 4 16 3-8h6',
    blue_dot: 'M29 37a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm-12-8h4m16 0h4',
    fortnight: 'M20 21h18v18H20Zm0 6h18M25 18v5m8-5v5',
    first_responder: 'M26 18h6v8h8v6h-8v8h-6v-8h-8v-6h8Z',
  }
  return (
    <svg viewBox="0 0 58 58" aria-hidden="true">
      <path d="M29 3 51 15.5v27L29 55 7 42.5v-27Z" fill={earned ? `${col}14` : 'none'} stroke={col} strokeOpacity={earned ? 0.9 : 0.4} strokeWidth="1.4" />
      <path d="M29 8 46.5 18v22L29 50 11.5 40V18Z" fill="none" stroke={col} strokeOpacity=".35" strokeWidth=".8" strokeDasharray="2 2" />
      <path d={glyph[id] ?? glyph.fortnight} fill="none" stroke={col} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" style={earned ? { filter: `drop-shadow(0 0 4px ${col})` } : undefined} />
    </svg>
  )
}

export function Avatar({ initials, size = '' }: { initials: string; size?: '' | 'lg' | 'xl' }) {
  return <span className={`avatar ${size}`}>{initials}</span>
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="card flat muted" style={{ textAlign: 'center', padding: 28 }}>{children}</div>
}

export function Loading({ what = 'telemetry' }: { what?: string }) {
  return <div className="page"><span className="lbl">Loading {what}…</span></div>
}
