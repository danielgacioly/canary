// Small readings of the detail the Health tab and the EVA card share.
import type { CrewDetail, HazardId, Indicator, Level, Risk, Alert } from '../api/types'

/** Bone is stored as the % change since launch; NASA's line is a share of the pre-flight value (standards.py: 100 - loss). */
export const bonePctOfPreflight = (i: Indicator) => 100 + i.value
export const gripPctOfPreflight = (i: Indicator) => (i.baseline ? (100 * i.value) / i.baseline : 100)

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
