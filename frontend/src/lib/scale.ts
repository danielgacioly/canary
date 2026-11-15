// Axis helpers for the Dashboard charts: a range that follows the data (never forced to zero) and round tick values.

/** About `n` round tick values inside [lo, hi] (steps of 1, 2, 2.5 or 5 times a power of ten). */
export function niceTicks(lo: number, hi: number, n = 4): number[] {
  const span = hi - lo
  if (!(span > 0)) return [lo]
  const raw = span / Math.max(1, n)
  const pow = Math.pow(10, Math.floor(Math.log10(raw)))
  const step = [1, 2, 2.5, 5, 10].map(m => m * pow).find(s => s >= raw) ?? 10 * pow
  const out: number[] = []
  for (let t = Math.ceil(lo / step - 1e-9) * step; t <= hi + step * 1e-9; t += step) out.push(+t.toPrecision(12))
  return out
}

/** Decimals needed to tell neighbouring ticks apart. */
export const tickDp = (ticks: number[]) => {
  if (ticks.length < 2) return 1
  const step = Math.abs(ticks[1] - ticks[0])
  return Math.min(3, Math.max(0, -Math.floor(Math.log10(step) + 1e-9)))
}

/** The data range plus every reference line, with room around it; `minSpan` stops tiny noise from filling the plot. */
export function domain(values: number[], minSpan = 0, pad = 0.12): [number, number] {
  let lo = Math.min(...values), hi = Math.max(...values)
  if (hi - lo < minSpan) { const m = (hi + lo) / 2; lo = m - minSpan / 2; hi = m + minSpan / 2 }
  const p = (hi - lo || Math.abs(hi) * 0.05 || 1) * pad
  return [lo - p, hi + p]
}

/** A chart point: a day and a value, or null on a day nobody measured. */
export type Pt = [number, number | null]
export type Known = [number, number]

/** The points that have a value. */
export const known = (pts: readonly Pt[]): Known[] => pts.filter((p): p is Known => p[1] !== null)

/** SVG path of a line that is lifted at every gap: it never joins two points with an unmeasured day between them. */
export function gapPath(pts: readonly Pt[], X: (x: number) => number, Y: (y: number) => number): string {
  let d = '', pen = false
  for (const [x, y] of pts) {
    if (y === null) { pen = false; continue }
    d += `${pen ? 'L' : 'M'}${X(x).toFixed(1)},${Y(y).toFixed(1)}`
    pen = true
  }
  return d
}

/** Trailing moving average over `win` days; a day without a value stays without one. */
export const movingAvg = (pts: readonly Pt[], win: number): Pt[] =>
  pts.map(([x, y], i) => {
    if (y === null) return [x, null]
    const w = known(pts.slice(Math.max(0, i - win + 1), i + 1))
    return [x, w.reduce((s, p) => s + p[1], 0) / w.length]
  })
