// "Ready for EVA?": the three numbers NASA-STD-3001 holds a spacewalker to, against the limit of the place you are in now.
// Personal: My space and the medical team's view only, never the crew pages. The data refetches when "Where you are"
// changes, so the colour follows the place.
import type { CrewDetail, Indicator, Level } from '../api/types'
import { bonePctOfPreflight, DASH, gripPctOfPreflight, num } from '../lib/health'
import { useSession } from '../state/session'

interface Row { id: string; name: string; now: string; limit: string; ind: Indicator | null; note?: string }

const VERDICT = ['Ready', 'Close to a limit', 'Below a limit'] as const

export default function EvaReadiness({ d, self = true, compact = false }: { d: CrewDetail; self?: boolean; compact?: boolean }) {
  const { catalog } = useSession()
  const sp = d.standard_profile
  const place = d.mission.place
  const who = self ? 'your' : `${d.crew.name.split(' ')[0]}'s`
  if (!sp) return null
  if (sp.eva === 'none') return <section className="eva"><h3>Ready for EVA?</h3><p className="muted">No EVA in {who} role.</p></section>
  if (d.mission.learning) {
    return <section className="eva"><h3>Ready for EVA?</h3><p className="muted">Nothing to check before launch: NASA's limits apply in flight.</p></section>
  }
  const lim = (catalog?.standards?.checked.vo2 ?? {}) as { surface?: number; microgravity?: number }
  const need = place.eva === 'surface' ? lim.surface : place.eva === 'microgravity' ? lim.microgravity : undefined
  const vo2 = d.indicators.vo2, grip = d.indicators.grip, bone = d.indicators.bone
  const rows: Row[] = []
  if (vo2.standard && need) rows.push({ id: 'vo2', name: 'VO2max', now: num(vo2.value, 1), limit: `${need} mL/kg/min`, ind: vo2 })
  else rows.push({ id: 'vo2', name: 'VO2max', now: num(vo2.value, 1), limit: '', ind: null, note: `No EVA at ${place.name}, so NASA sets no minimum here.` })
  if (grip.standard) rows.push({ id: 'grip', name: 'Grip strength', now: grip.value === null ? DASH : `${num(gripPctOfPreflight(grip))}%`, limit: '80% of pre-flight', ind: grip })
  if (bone.standard) rows.push({ id: 'bone', name: 'Bone density', now: bone.value === null ? DASH : `${num(bonePctOfPreflight(bone), 1)}%`, limit: '95% of pre-flight', ind: bone })
  const level = Math.max(0, ...rows.map(r => r.ind?.standard?.level ?? 0)) as Level
  return (
    <section className={`eva s${level}`}>
      <div className="eva-head">
        <h3>Ready for EVA?</h3>
        <span className="status"><span className="dot" />{VERDICT[level]}</span>
      </div>
      {need && (
        <p className="small muted">
          At {place.name} NASA asks {need} mL/kg/min of VO2max{place.eva === 'surface' && lim.microgravity ? `, against ${lim.microgravity} for microgravity EVAs, so the same fitness can pass in orbit and fall short here` : ''}.
        </p>
      )}
      <ul className="eva-rows">
        {rows.map(r => {
          const s = r.ind?.standard
          return (
            <li key={r.id} className={`s${s?.level ?? 0}`}>
              <span className="dot" style={s ? undefined : { background: 'var(--line-2)' }} />
              <span className="n">{r.name}</span>
              <span className="v num">{r.now}{r.limit && <span className="dim"> · NASA asks {r.limit}</span>}</span>
              {s && <a className="item" href={s.url} target="_blank" rel="noreferrer" title={s.source}>{s.item}</a>}
              {r.note && <span className="small dim eva-note">{r.note}</span>}
              {s && (!compact || s.level > 0) && <span className="small muted eva-note">{s.text}</span>}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
