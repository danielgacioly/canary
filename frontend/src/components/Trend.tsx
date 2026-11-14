// Dashboard charts: the axis follows the data, the legend sits above the plot (not on the line), and the
// drawing is made at the real pixel width so the labels keep one size on a phone and on a desktop.
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { domain, movingAvg, niceTicks, tickDp } from '../lib/scale'

function useWidth() {
  const ref = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    setW(Math.floor(el.clientWidth))
    const ro = new ResizeObserver(() => setW(Math.floor(el.clientWidth)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

export interface Tick { x: number; label: string }
type Scale = (v: number) => number

/** Axes and grid; `children` draws the data with the two scales. */
export function Plot({ x, y, xTicks, h = 150, label, children }:
  { x: [number, number]; y: [number, number]; xTicks: Tick[]; h?: number; label: string; children: (X: Scale, Y: Scale) => ReactNode }) {
  const [ref, w] = useWidth()
  const yt = niceTicks(y[0], y[1], 4), dp = tickDp(yt)
  const fmt = (t: number) => t.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
  const P = { l: 12 + 7 * Math.max(...yt.map(t => fmt(t).length), 2), r: 8, t: 8, b: 22 }
  const X: Scale = v => P.l + ((v - x[0]) / (x[1] - x[0] || 1)) * (w - P.l - P.r)
  const Y: Scale = v => h - P.b - ((v - y[0]) / (y[1] - y[0] || 1)) * (h - P.t - P.b)
  return (
    <div ref={ref} className="plot" style={{ height: h }}>
      {w > 0 && (
        <svg className="chart" width={w} height={h} role="img" aria-label={label}>
          {yt.map(t => (
            <g key={t}>
              <line className="gl" x1={P.l} x2={w - P.r} y1={Y(t)} y2={Y(t)} />
              <text className="num" x={P.l - 8} y={Y(t) + 4} textAnchor="end">{fmt(t)}</text>
            </g>
          ))}
          {children(X, Y)}
          {xTicks.map((t, i) => (
            <text key={t.label} className="num" x={X(t.x)} y={h - 6} textAnchor={i === 0 ? 'start' : i === xTicks.length - 1 ? 'end' : 'middle'}>{t.label}</text>
          ))}
        </svg>
      )}
    </div>
  )
}

/** One indicator over the last days: its line, the person's normal (dashed) and, in flight, the NASA limit. */
export default function Trend({ pts, color, baseline, limit, minSpan = 0, avg, label }:
  { pts: [number, number][]; color: string; baseline?: number; limit?: number; minSpan?: number; avg?: number; label: string }) {
  if (pts.length < 2) return <p className="small dim">Not enough days yet.</p>
  const dom = domain(pts.map(p => p[1]).concat(baseline ?? [], limit ?? []), minSpan)
  const x0 = pts[0][0], x1 = pts[pts.length - 1][0]
  const line = (a: [number, number][], X: Scale, Y: Scale) => a.map((p, j) => `${j ? 'L' : 'M'}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('')
  const xTicks: Tick[] = [x0, Math.round((x0 + x1) / 2), x1].map(d => ({ x: d, label: `day ${d}` }))
  return (
    <Plot x={[x0, x1]} y={dom} xTicks={xTicks} label={label}>
      {(X, Y) => (
        <>
          {baseline !== undefined && <line x1={X(x0)} x2={X(x1)} y1={Y(baseline)} y2={Y(baseline)} stroke="var(--muted)" strokeDasharray="4 4" />}
          {limit !== undefined && <line x1={X(x0)} x2={X(x1)} y1={Y(limit)} y2={Y(limit)} stroke="var(--act)" strokeWidth="1.4" />}
          {avg ? (
            <>
              {pts.map(p => <circle key={p[0]} cx={X(p[0])} cy={Y(p[1])} r="2.2" fill={color} opacity=".35" />)}
              <path d={line(movingAvg(pts, avg), X, Y)} fill="none" stroke={color} strokeWidth="2" />
            </>
          ) : (
            <>
              <path d={line(pts, X, Y)} fill="none" stroke={color} strokeWidth="1.8" />
              <circle cx={X(x1)} cy={Y(pts[pts.length - 1][1])} r="2.8" fill={color} />
            </>
          )}
        </>
      )}
    </Plot>
  )
}
