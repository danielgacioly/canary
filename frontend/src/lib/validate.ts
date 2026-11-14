// Input rules for every form. Each rule takes what the person typed and returns a sentence that names the field,
// the number and the unit ("Pulse must be between 25 and 250 bpm"), or null when the value is fine.
// The server repeats every rule (backend/canary/domain/validation.py and the Pydantic models in main.py):
// this file only saves the person a round trip. The numeric ranges are typing limits, not clinical ranges.

export type Rule<V = string> = (value: V) => string | null

/** The first message of a list of rules, or null. */
export const all = <V,>(...rules: Rule<V>[]): Rule<V> => v => {
  for (const r of rules) { const m = r(v); if (m) return m }
  return null
}

const withUnit = (unit?: string) => (unit ? ` ${unit}` : '')
const blank = (v: unknown) => v === null || v === undefined || (typeof v === 'string' && v.trim() === '')

/** Reads a typed number. A comma counts as the decimal separator. Returns null for anything that is not a plain number. */
export function parseNumber(s: string): number | null {
  const t = s.trim().replace(',', '.')
  if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(t)) return null
  const n = Number(t)
  return Number.isFinite(n) ? n : null
}

export const required = (label: string): Rule<string> => v => (blank(v) ? `${label} is required` : null)

interface NumberOpts { min?: number; max?: number; unit?: string; integer?: boolean; decimals?: number; optional?: boolean }

/** A number typed as text. Empty is an error unless `optional`. */
export function number(label: string, o: NumberOpts = {}): Rule<string> {
  return v => {
    if (blank(v)) return o.optional ? null : `${label} is required`
    const n = parseNumber(v)
    if (n === null) return `${label} must be a number${o.unit ? `, in ${o.unit}` : ''}`
    if (o.integer && !Number.isInteger(n)) return `${label} must be a whole number`
    if (o.decimals !== undefined && !o.integer) {
      const f = 10 ** o.decimals
      if (Math.abs(Math.round(n * f) / f - n) > 1e-9) return `${label} can have at most ${o.decimals} decimal place${o.decimals === 1 ? '' : 's'}`
    }
    const { min, max } = o
    if (min !== undefined && max !== undefined && (n < min || n > max)) return `${label} must be between ${min} and ${max}${withUnit(o.unit)}`
    if (min !== undefined && n < min) return `${label} must be at least ${min}${withUnit(o.unit)}`
    if (max !== undefined && n > max) return `${label} must be at most ${max}${withUnit(o.unit)}`
    return null
  }
}

/** Text with a trimmed length. Spaces alone do not count. Empty is an error unless `optional`. */
export function length(label: string, o: { min?: number; max?: number; optional?: boolean } = {}): Rule<string> {
  return v => {
    const n = v.trim().length
    if (n === 0) return o.optional ? null : `${label} is required`
    if (o.min !== undefined && n < o.min) return `${label} must be at least ${o.min} characters`
    if (o.max !== undefined && v.length > o.max) return `${label} must be at most ${o.max} characters (now ${v.length})`
    return null
  }
}

/** A hint such as "25–250 bpm" built from the same numbers the rule uses. */
export const range = (min: number, max: number, unit?: string) => `${min}–${max}${withUnit(unit)}`

const isoDay = /^(\d{4})-(\d{2})-(\d{2})$/
/** Parses YYYY-MM-DD as a real calendar date (UTC midnight), or null. */
export function parseDay(s: string): Date | null {
  const m = isoDay.exec(s)
  if (!m) return null
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]))
  return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3] ? d : null
}

/** A real date inside a window of years (inclusive). */
export function date(label: string, o: { minYear?: number; maxYear?: number } = {}): Rule<string> {
  return v => {
    if (blank(v)) return `${label} is required`
    const d = parseDay(v)
    if (!d) return `${label} is not a real date`
    const y = d.getUTCFullYear()
    if ((o.minYear !== undefined && y < o.minYear) || (o.maxYear !== undefined && y > o.maxYear)) return `${label} must be between ${o.minYear ?? 'any year'} and ${o.maxYear ?? 'any year'}`
    return null
  }
}

export function ageOn(dob: Date, day: Date): number {
  const had = day.getUTCMonth() > dob.getUTCMonth() || (day.getUTCMonth() === dob.getUTCMonth() && day.getUTCDate() >= dob.getUTCDate())
  return day.getUTCFullYear() - dob.getUTCFullYear() - (had ? 0 : 1)
}

/** A date of birth that gives an age between `min` and `max` on the launch day. */
export function ageAtLaunch(label: string, launch: string, min: number, max: number): Rule<string> {
  const base = date(label)
  return v => {
    const m = base(v)
    if (m) return m
    const l = parseDay(launch)
    if (!l) return null // the launch date has its own error
    const age = ageOn(parseDay(v) as Date, l)
    return age < min || age > max ? `${label} gives an age of ${age} at launch; it must be between ${min} and ${max}` : null
  }
}

/** A 24-hour time, HH:MM. */
export const time = (label: string): Rule<string> => v => {
  if (blank(v)) return `${label} is required`
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(v) ? null : `${label} must be a time like 23:30`
}

/** Exactly four digits. */
export const pin4 = (label = 'PIN'): Rule<string> => v => (blank(v) ? `${label} is required` : /^\d{4}$/.test(v) ? null : `${label} must be exactly 4 digits`)

/** One of a closed list. Empty is an error unless `optional`. */
export const oneOf = (label: string, options: readonly string[], optional = false): Rule<string> => v => {
  if (blank(v)) return optional ? null : `${label} is required`
  return options.includes(v) ? null : `${label} must be one of: ${options.join(', ')}`
}

/** Hours between two HH:MM clock times, going past midnight when the wake time is earlier. Null when a time is not valid. */
export function sleepHours(bed: string, wake: string): number | null {
  if (time('')(bed) || time('')(wake)) return null
  const [bh, bm] = bed.split(':').map(Number), [wh, wm] = wake.split(':').map(Number)
  const mins = (((wh * 60 + wm) - (bh * 60 + bm)) % 1440 + 1440) % 1440
  return Math.round(mins / 6) / 10
}

/** A picture to upload: PNG, JPEG or WebP, at most `maxMb`. Returns the message, or null when the file is fine. */
export function imageFile(f: File, maxMb = 8): string | null {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(f.type)) return 'The photo must be a PNG, JPEG or WebP image'
  if (f.size > maxMb * 1024 * 1024) return `The photo must be at most ${maxMb} MB (this one is ${(f.size / 1048576).toFixed(1)} MB)`
  return null
}
