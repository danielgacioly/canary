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

/** Trailing moving average over `win` points. */
export const movingAvg = (pts: [number, number][], win: number): [number, number][] =>
  pts.map(([x], i) => {
    const w = pts.slice(Math.max(0, i - win + 1), i + 1)
    return [x, w.reduce((s, p) => s + p[1], 0) / w.length]
  })
