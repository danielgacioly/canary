// Small readings of the detail the Health tab and the EVA card share.
import type { CrewDetail, HazardId, Indicator, Level, Risk, Alert } from '../api/types'

/** Bone is stored as the % change since launch; NASA's line is a share of the pre-flight value (standards.py: 100 - loss). */
export const bonePctOfPreflight = (i: Indicator): number | null => (i.value === null ? null : 100 + i.value)
export const gripPctOfPreflight = (i: Indicator): number | null => (i.value === null ? null : i.baseline ? (100 * i.value) / i.baseline : 100)

/** What stands where a number is missing. */
export const DASH = '—'
/** A number to a fixed number of decimals, or the dash when there is none. */
export const num = (v: number | null | undefined, dp = 0): string => (v === null || v === undefined ? DASH : v.toFixed(dp))
/** The indicator's value with its decimals, or the dash. */
export const fmtValue = (i: Indicator): string => num(i.value, i.dp)
/** True when there is no current value for the indicator (never measured, or the last reading is too old to count). */
export const noValue = (i: Indicator): boolean => i.value === null
/** True when no indicator of the list has a current value. */
export const allMissing = (inds: Indicator[]): boolean => inds.length > 0 && inds.every(noValue)

/** The quiet line under a number that is missing, or that is still being learned. Null when there is nothing to say. */
export function missingNote(i: Indicator): string | null {
  if (i.value === null) {
    if (i.last_measured_day !== null) return `Last measured day ${i.last_measured_day}`
    return 'No data yet'
  }
  return learningNote(i)
}

/** "Learning your normal: 2 of 5" while the person has too few measurements to have a normal of their own. */
export function learningNote(i: Indicator): string | null {
  if (i.baseline_from === 'learning' || (i.learning && i.baseline === null)) return `Learning your normal: ${i.baseline_n} of ${i.baseline_need ?? 5}`
  return null
}

/** The word for where the dose in a person's page comes from; nothing for a dose that is fully measured or unknown. */
export function doseOrigin(d: { origin?: 'measured' | 'partial' | 'estimated' }): string | null {
  return d.origin === 'estimated' ? 'estimated' : d.origin === 'partial' ? 'partly measured' : null
}

/** Last Amsler grid in the recent check-ins, as a short value. */
export function amslerResult(d: CrewDetail): { label: string; day: number | null; level: Level } {
  const e = d.events.find(x => x.kind === 'amsler')
  if (!e) return { label: 'Not done', day: null, level: 0 }
  return e.payload.distortion ? { label: 'Distorted', day: e.day, level: 2 } : { label: 'Clear', day: e.day, level: 0 }
}

/** True when any indicator of the system is raised by a NASA-STD-3001 limit. */
export const nasaRaises = (d: CrewDetail, inds: string[]) => inds.some(k => (d.indicators[k]?.standard?.level ?? 0) > 0)

export interface Attention { key: string; level: Level; title: string; since?: number; hazards: HazardId[]; sys?: string | null }

/** Alerts and risks above level 0 as one list. A risk an alert already tells about is not listed twice. */
export function attention(alerts: Alert[], risks: Risk[]): Attention[] {
  const told = new Set(alerts.map(a => a.risk).filter(Boolean))
  const rows: Attention[] = [
    ...alerts.filter(a => a.level > 0).map(a => ({ key: `a-${a.id}`, level: a.level, title: a.title, since: a.since_day, hazards: a.hazards ?? [], sys: a.sys })),
    ...risks.filter(r => r.level > 0 && !told.has(r.id)).map(r => ({ key: `r-${r.id}`, level: r.level, title: r.name, since: r.since_day ?? undefined, hazards: r.hazards, sys: r.systems[0] })),
  ]
  return rows.sort((a, b) => b.level - a.level || (a.since ?? 1e9) - (b.since ?? 1e9))
}

/** The NASA line a chart draws, in the chart's own unit. VO2max: the item (V1 4001 microgravity EVA, V1 4002 surface EVA) says which
 *  minimum applies today (standards.py LIMITS); strength: 80% of the pre-flight value; bone: 95% of pre-flight. Only in flight. */
export function nasaLine(k: string, i: Indicator): { y: number; text: string; item: string; url: string } | null {
  const s = i.standard
  if (!s) return null
  const base = { item: s.item, url: s.url }
  if (k === 'vo2') return { ...base, y: s.item === 'V1 4001' ? 32.9 : 36.5, text: `${s.item === 'V1 4001' ? 32.9 : 36.5} ${i.unit}` }
  if (k === 'grip' && i.baseline !== null && i.baseline) return { ...base, y: 0.8 * i.baseline, text: `${(0.8 * i.baseline).toFixed(i.dp)} ${i.unit} (80% of pre-flight)` }
  if (k === 'bone') return { ...base, y: 95, text: '95% of pre-flight' }
  return null
}

/** Words for where an indicator's numbers come from, the same on every chart. */
export const ORIGIN = { simulated: 'Simulated', real: 'Real NASA data', user: 'You typed', none: 'Not measured' } as const
