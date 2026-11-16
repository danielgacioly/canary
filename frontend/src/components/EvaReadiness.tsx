// "EVA check": the three numbers NASA-STD-3001 holds a spacewalker to, against the limit of the place you are in now.
// The verdict is "Displayed criteria met" only when the displayed numbers were judged against a limit and no restriction
// is active (duty status, or the care window after an emergency). It never says more than the three numbers show.
// Personal: My space and the medical team's view only, never the crew pages. The data refetches when "Where you are"
// changes, so the colour follows the place.
import type { CrewDetail, Indicator, Level } from '../api/types'
import { assessWord, bonePctOfPreflight, DASH, genericLimit, gripPctOfPreflight, num } from '../lib/health'
import { useSession } from '../state/session'

interface Row { id: string; name: string; now: string; limit: string; ind: Indicator | null; note?: string }

const VERDICT = ['Displayed criteria met', 'Close to a limit', 'Below a limit'] as const

export default function EvaReadiness({ d, self = true, compact = false }: { d: CrewDetail; self?: boolean; compact?: boolean }) {
  const { catalog } = useSession()
  const lim = catalog?.limits
  const sp = d.standard_profile
  const place = d.mission.place
  const who = self ? 'your' : `${d.crew.name.split(' ')[0]}'s`
  if (!sp) return null
  if (sp.eva === 'none') return <section className="eva"><h3>EVA check</h3><p className="muted">No EVA in {who} role.</p></section>
  if (d.mission.learning) {
    return <section className="eva"><h3>EVA check</h3><p className="muted">Nothing to check before launch: NASA's limits apply in flight.</p></section>
  }
  const need = place.eva === 'surface' ? lim?.vo2.surface : place.eva === 'microgravity' ? lim?.vo2.microgravity : undefined
  const vo2 = d.indicators.vo2, grip = d.indicators.grip, bone = d.indicators.bone
  const rows: Row[] = []
  if (vo2.standard && need && lim) rows.push({ id: 'vo2', name: 'VO2max', now: num(vo2.value, 1), limit: `${need} ${lim.vo2.unit}`, ind: vo2 })
  else rows.push({ id: 'vo2', name: 'VO2max', now: num(vo2.value, 1), limit: '', ind: null, note: `No EVA at ${place.name}, so NASA sets no minimum here.` })
  rows.push({ id: 'grip', name: 'Grip strength', now: grip.value === null ? DASH : `${num(gripPctOfPreflight(grip))}%`, limit: genericLimit('grip', lim) ?? '', ind: grip })
  rows.push({ id: 'bone', name: 'Bone density', now: bone.value === null ? DASH : `${num(bonePctOfPreflight(bone), 1)}%`, limit: genericLimit('bone', lim) ?? '', ind: bone })
  // Judged: a number held against a NASA limit today. Anything else is not a verdict.
  const judged = rows.filter(r => r.ind?.standard && r.ind.value !== null && (r.ind.standard.status as string) !== 'not_assessable')
  const level = Math.max(0, ...judged.map(r => r.ind?.standard?.level ?? 0)) as Level
  // Restrictions: a duty status other than full, or a care window after an emergency. They block the verdict.
  const ops = d.ops
  const restricted = !!ops && ops.key !== 'full'
  const verdict = judged.length === 0
    ? (rows.some(r => r.ind?.value !== null) ? 'Not assessed' : 'No data yet')
    : restricted ? 'Restricted, not cleared' : VERDICT[level]
  const tone = judged.length === 0 ? 'nodata' : `s${restricted ? Math.max(level, 1) : level}`
  return (
    <section className={`eva ${tone} ${compact ? 'compact' : ''}`}>
      <div className="eva-head">
        <h3>EVA check</h3>
        <span className="status"><span className="dot" />{verdict}</span>
      </div>
      {restricted && !compact && (
        <p className="small eva-note">
          {ops?.until_day !== undefined ? `Care window: restricted until day ${ops.until_day}` : `Duty status: ${ops?.label}`}
          {ops?.reason ? ` · ${ops.reason}` : ''}
        </p>
      )}
      {need && !compact && lim && (
        <p className="small muted">
          At {place.name} NASA asks {need} {lim.vo2.unit} of VO2max{place.eva === 'surface' && lim.vo2.microgravity ? `, against ${lim.vo2.microgravity} for microgravity EVAs, so the same fitness can pass in orbit and fall short here` : ''}.
        </p>
      )}
      <ul className="eva-rows">
        {rows.map(r => {
          const s = r.ind?.standard
          const word = r.ind && r.ind.value === null ? assessWord(r.ind.assessment ?? 'insufficient_data') : null
          return (
            <li key={r.id} className={`s${s?.level ?? 0}`}>
              <span className="dot" style={s ? undefined : { background: 'var(--line-2)' }} />
              <span className="n">{r.name}</span>
              <span className="v num">{r.now}{r.limit && <span className="dim"> · NASA asks {r.limit}</span>}{word && <span className="dim"> · {word}</span>}</span>
              {s && !compact && <a className="item" href={s.url} target="_blank" rel="noreferrer" title={s.source}>{s.item}</a>}
              {r.note && <span className="small dim eva-note">{r.note}</span>}
              {s && (!compact || s.level > 0) && <span className="small muted eva-note">{s.text}</span>}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
