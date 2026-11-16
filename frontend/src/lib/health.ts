// Small readings of the detail the Health tab and the EVA card share.
import type { Assessment, CrewDetail, HazardId, Indicator, Level, LimitsMeta, Risk, Alert } from '../api/types'

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

/** "Learning your normal (2 of 5 readings)" while the person has too few measurements to have a normal of their own.
 *  The count leaves out today's reading, so with none counted yet it says how many are needed instead of "0 of 5". */
export function learningNote(i: Indicator): string | null {
  if (!(i.baseline_from === 'learning' || (i.learning && i.baseline === null))) return null
  const need = i.baseline_need ?? 5
  return i.baseline_n > 0 ? `Learning your normal (${i.baseline_n} of ${need} readings)` : `Learning your normal (needs ${need} readings)`
}

/** True when at least one indicator has a current value and a normal of the person's own to compare it with.
 *  Without one, nothing can be called "within your normal". */
export const hasOwnNormal = (d: CrewDetail): boolean => Object.values(d.indicators).some(i => i.value !== null && i.baseline !== null)

/** When something started, counted back from the day being looked at: "started today", "started 5 days ago". */
export function startedText(since: number | null | undefined, today: number): string | null {
  if (since === null || since === undefined) return null
  const n = today - since
  if (n <= 0) return 'started today'
  return n === 1 ? 'started yesterday' : `started ${n} days ago`
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

/** The NASA line a chart draws, in the chart's own unit, read from the backend's limits (GET /api/catalog `limits`).
 *  VO2max: the item (V1 4001 microgravity EVA, V1 4002 surface EVA) says which minimum applies today; strength: the
 *  limit % of the pre-flight value; bone: the limit % of pre-flight. Only in flight. */
export function nasaLine(k: string, i: Indicator, lim?: LimitsMeta): { y: number; text: string; item: string; url: string } | null {
  const s = i.standard
  if (!s || !lim) return null
  const base = { item: s.item, url: s.url }
  if (k === 'vo2') {
    const y = s.item === 'V1 4001' ? lim.vo2.microgravity : lim.vo2.surface
    return { ...base, y, text: `${y} ${lim.vo2.unit}` }
  }
  if (k === 'grip' && i.baseline !== null && i.baseline) {
    const y = (lim.grip.limit_pct / 100) * i.baseline
    return { ...base, y, text: `${y.toFixed(i.dp)} ${i.unit} (${lim.grip.limit_pct}% of pre-flight)` }
  }
  if (k === 'bone') return { ...base, y: lim.bone.limit_pct, text: `${lim.bone.limit_pct}% of pre-flight` }
  return null
}

/** The short NASA limit of an indicator that has one (a percent of pre-flight), for tables; null for the others. */
export function genericLimit(k: string, lim?: LimitsMeta): string | null {
  if (!lim) return null
  if (k === 'grip') return `${lim.grip.limit_pct}% of pre-flight`
  if (k === 'bone') return `${lim.bone.limit_pct}% of pre-flight`
  return null
}

/** The words a screen shows in place of a value when the state is not "assessed". Null when it is assessed. */
export const ASSESS_WORD: Record<Assessment, string | null> = { assessed: null, insufficient_data: 'No data', stale_data: 'Stale', not_applicable: 'Not applicable' }
/** True when the state is anything but assessed: such a value never gets a normal (green) look. */
export const notAssessed = (a?: Assessment): boolean => !!a && a !== 'assessed'
/** The label of a non-assessed state, or null. */
export const assessWord = (a?: Assessment): string | null => (a ? ASSESS_WORD[a] : null)

/** Words for where an indicator's numbers come from, the same on every chart. */
export const ORIGIN = { simulated: 'Simulated', real: 'Real NASA data', user: 'You typed', none: 'Not measured' } as const
