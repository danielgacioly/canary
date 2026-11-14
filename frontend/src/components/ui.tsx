// Small shared pieces: icons, status, sparkline, line chart, mission patches.
import { useEffect, useState, type ReactNode } from 'react'
import type { Level } from '../api/types'

export const STATUS = ['On track', 'Watch', 'Act'] as const

const paths: Record<string, string> = {
  check: 'm5 12 4.5 4.5L19 7',
  close: 'M6 6l12 12M18 6 6 18',
  chev: 'm9 6 6 6-6 6',
  back: 'm15 6-6 6 6 6',
  send: 'm4 12 16-8-6 16-2.5-6.5L4 12Z',
  ask: 'M4 5h16v11H9l-5 4V5Z',
  today: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 9a7 7 0 0 1 14 0',
  goals: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-4a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm0-4a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z',
  rank: 'M7 21V11m5 10V5m5 16v-7',
  crew: 'M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm-6 9a6 6 0 0 1 12 0m1.5-9a3 3 0 1 0 0-6m2.5 15a5 5 0 0 0-3-4.6',
  plan: 'M4 6h4v4H4Zm12 8h4v4h-4ZM8 8h4a2 2 0 0 1 2 2v4a2 2 0 0 0 2 2',
  weather: 'M12 3v2m0 14v2M3 12h2m14 0h2M6 6l1.5 1.5m9 9L18 18M18 6l-1.5 1.5m-9 9L6 18M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z',
  link: 'M4 12a8 8 0 0 1 16 0M7.5 12a4.5 4.5 0 0 1 9 0M12 12v8',
  med: 'M10 4h4v6h6v4h-6v6h-4v-6H4v-4h6V4Z',
  info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-11v6m0-9v.01',
  plus: 'M12 5v14M5 12h14',
  lock: 'M6 11h12v9H6Zm2.5 0V8a3.5 3.5 0 0 1 7 0v3',
  open: 'M6 11h12v9H6Zm2.5 0V8a3.5 3.5 0 0 1 6.8-1.2',
  backspace: 'M21 5H9l-6 7 6 7h12V5Zm-4 4-6 6m0-6 6 6',
  shield: 'M12 3 5 6v5c0 4.5 3 8.3 7 10 4-1.7 7-5.5 7-10V6l-7-3Z',
  test: 'M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3M7 15h10',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7.5 7.5 0 0 0-2-1.2L14.5 3h-5l-.4 2.6a7.5 7.5 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7.5 7.5 0 0 0 2 1.2l.4 2.6h5l.4-2.6a7.5 7.5 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z',
  sun: 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm0-13v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4',
  moon: 'M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z',
}
export function Icon({ name, size = 16 }: { name: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[name] ?? paths.chev} />
    </svg>
  )
}

export function CanaryMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <path d="M3 9l5 3-1 4c0 6 5 11 12 11 5 0 8-3 8-7 0-3-2-5-4-6-1-1-1-3-3-4-3-2-6-1-8 1L3 9z" fill="#f2c230" />
      <circle cx="12" cy="13" r="1.4" fill="#0b0d11" />
    </svg>
  )
}

export function Status({ level, children }: { level: Level | number; children?: ReactNode }) {
  return <span className={`status s${level}`}><span className="dot" />{children ?? STATUS[level]}</span>
}

/** Line with the personal baseline dashed. No fill, no glow. */
export function Spark({ data, base, color = 'var(--muted)', w = 140, h = 36 }: { data: [number, number][]; base?: number; color?: string; w?: number; h?: number }) {
  if (!data.length) return null
  const ys = data.map(d => d[1]).concat(base ?? [])
  const lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1
  const X = (i: number) => (i / (data.length - 1)) * w, Y = (v: number) => h - 3 - ((v - lo) / span) * (h - 6)
  const line = data.map((d, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(d[1]).toFixed(1)}`).join('')
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      {base !== undefined && <line x1="0" x2={w} y1={Y(base)} y2={Y(base)} stroke="var(--dim)" strokeDasharray="3 3" />}
      <path d={line} fill="none" stroke={color} strokeWidth="1.6" />
      <circle cx={X(data.length - 1)} cy={Y(data[data.length - 1][1])} r="2.5" fill={color} />
    </svg>
  )
}

export function LineChart({ series, w = 560, h = 190, xLabels, refY, refLabel }:
  { series: { pts: [number, number][]; color: string }[]; w?: number; h?: number; xLabels?: string[]; refY?: number; refLabel?: string }) {
  const all = series.flatMap(s => s.pts)
  const xs = all.map(p => p[0]), ys = all.map(p => p[1]).concat(refY ?? [])
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(0, ...ys), y1 = Math.max(...ys) * 1.08
  const P = { l: 44, r: 10, t: 10, b: 24 }
  const X = (x: number) => P.l + ((x - x0) / (x1 - x0 || 1)) * (w - P.l - P.r)
  const Y = (y: number) => h - P.b - ((y - y0) / (y1 - y0 || 1)) * (h - P.t - P.b)
  const ticks = [0, 0.5, 1].map(k => y0 + k * (y1 - y0))
  return (
    <svg className="chart" viewBox={`0 0 ${w} ${h}`} width="100%" aria-hidden="true">
      {ticks.map((t, i) => <g key={i}><line className="gl" x1={P.l} x2={w - P.r} y1={Y(t)} y2={Y(t)} /><text x={P.l - 8} y={Y(t) + 4} textAnchor="end">{t >= 1000 ? `${(t / 1000).toFixed(1)}k` : t.toFixed(t < 10 ? 1 : 0)}</text></g>)}
      {refY !== undefined && <><line x1={P.l} x2={w - P.r} y1={Y(refY)} y2={Y(refY)} stroke="var(--muted)" strokeDasharray="4 4" /><text x={w - P.r} y={Y(refY) - 6} textAnchor="end">{refLabel}</text></>}
      {series.map((s, i) => <path key={i} d={s.pts.map((p, j) => `${j ? 'L' : 'M'}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('')} fill="none" stroke={s.color} strokeWidth="1.8" />)}
      {xLabels?.map((l, i) => <text key={i} x={P.l + (i / (xLabels.length - 1)) * (w - P.l - P.r)} y={h - 6} textAnchor={i === 0 ? 'start' : i === xLabels.length - 1 ? 'end' : 'middle'}>{l}</text>)}
    </svg>
  )
}

/** Mission patch: plain line art. Colour only when earned. */
export function Patch({ id, earned }: { id: string; earned: boolean }) {
  const col = earned ? 'var(--gold)' : 'var(--dim)'
  const glyph: Record<string, string> = {
    iron_bones: 'M14 26l12-12m-10 1.5a2.5 2.5 0 1 1-3-3 2.5 2.5 0 1 1 3 3Zm12 12a2.5 2.5 0 1 1 3-3 2.5 2.5 0 1 1-3 3Z',
    hydro: 'M20 11s-7 8-7 13a7 7 0 0 0 14 0c0-5-7-13-7-13Z',
    still_water: 'M11 24c3-2.5 6-2.5 9 0s6 2.5 9 0M11 19c3-2.5 6-2.5 9 0s6 2.5 9 0',
    deep_reader: 'M20 14c-3-1.5-6-1.5-9-.5v14c3-1 6-1 9 .5 3-1.5 6-1.5 9-.5v-14c-3-1-6-1-9 .5Zm0 0v14',
    crew_glue: 'M16 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm8 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM11 29a5 5 0 0 1 10 0m-2 0a5 5 0 0 1 10 0',
    honest_signal: 'M10 20h5l3-7 4 14 3-7h5',
    blue_dot: 'M20 26a6 6 0 1 0 0-12 6 6 0 0 0 0 12Z',
    fortnight: 'M12 13h16v15H12Zm0 5h16M16 10v4m8-4v4',
    first_responder: 'M17 11h6v6h6v6h-6v6h-6v-6h-6v-6h6Z',
  }
  return (
    <svg viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="20" r="18.5" fill="none" stroke={col} strokeWidth="1.2" />
      <path d={glyph[id] ?? glyph.fortnight} fill="none" stroke={col} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function Avatar({ initials, size = '' }: { initials: string; size?: '' | 'lg' | 'xl' }) {
  return <span className={`avatar ${size}`}>{initials}</span>
}

export function Loading({ what = 'data' }: { what?: string }) {
  return <div className="page"><span className="lbl">Loading {what}…</span></div>
}

export function Tabs<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {options.map(([k, l]) => <button key={k} role="tab" aria-selected={value === k} className={value === k ? 'on' : ''} onClick={() => onChange(k)}>{l}</button>)}
    </div>
  )
}

/** Count up to a number when it first appears. */
export function CountUp({ value, dp = 0, ms = 1100 }: { value: number; dp?: number; ms?: number }) {
  const [v, setV] = useState(0)
  useEffect(() => {
    let raf = 0
    const t0 = performance.now()
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / ms)
      setV(value * (1 - Math.pow(1 - k, 3)))
      if (k < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [value, ms])
  return <>{v.toFixed(dp)}</>
}

export const PLACE_CLASS = (loc: string) => `p-${loc}`
