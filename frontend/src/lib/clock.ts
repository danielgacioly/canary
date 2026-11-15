// The mission date the clock shows next to the mission day: "26 Oct 2035".
import type { Clock } from '../api/types'

export function clockDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}

export const clockLine = (c: Clock): string => clockDate(c.date)
