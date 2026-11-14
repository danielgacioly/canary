// People as dots. A dot shows only what the whole crew may see: the operational status.
// Health details live behind each astronaut's own entry (see EnterGate).
import { useNavigate } from 'react-router-dom'
import type { Person } from '../api/types'
import { useSession } from '../state/session'
import { Icon } from './ui'

export const OPS_SHORT = { full: 'Fit for all duties', limited: 'Fit, no EVA', rest: 'Off critical tasks' } as const

export function Dot({ p, size = 'md', me = false, title }: { p: Pick<Person, 'initials' | 'ops' | 'name'>; size?: 'sm' | 'md' | 'xl'; me?: boolean; title?: string }) {
  return (
    <span className={`pdot ${size} s${p.ops.level} ${me ? 'me' : ''}`} title={title ?? `${p.name}: ${p.ops.label}`}>
      <span className="ini">{p.initials}</span>
      <i />
    </span>
  )
}

/** The crew in the top bar, as in the first prototype: tap a dot to open that person. */
export function CrewDots({ people }: { people: Person[] }) {
  const { me } = useSession()
  const nav = useNavigate()
  return (
    <div className="crewdots" role="group" aria-label="Crew">
      {people.map(p => (
        <button key={p.id} onClick={() => nav(p.id === me ? '/today' : `/crew/${p.id}`)} aria-label={`${p.name}: ${p.ops.label}`}>
          <Dot p={p} size="sm" me={p.id === me} />
        </button>
      ))}
    </div>
  )
}

/** Shown wherever personal data would appear and nobody has entered their space. */
export function EnterGate({ what = 'your health' }: { what?: string }) {
  const { catalog, setMe, mission } = useSession()
  if (!catalog) return null
  return (
    <div className="page">
      <section className="gate detail-card rise">
        <span className="lock"><Icon name="lock" size={22} /></span>
        <span className="eyebrow">Private space</span>
        <h1>Enter to see {what}.</h1>
        <p className="muted">Your numbers, alerts and advice are yours. The crew sees only whether you are fit for duty. Only you and the medical team see the rest, unless you choose to share it.</p>
        <div className="gate-people">
          {catalog.crew.map((c, i) => (
            <button key={c.id} className="rise" style={{ ['--d' as string]: i + 1 }} onClick={() => setMe(c.id)}>
              <span className={`pdot md ${mission?.suggested_user === c.id ? 'me' : ''}`}><span className="ini">{c.initials}</span></span>
              <b>{c.name.split(' ')[0]}</b><span className="small muted">{c.role}</span>
            </button>
          ))}
        </div>
        <p className="small dim">No accounts on board: tap your name. Closing this window locks your space again.{mission ? ` The demo story is following ${catalog.crew.find(c => c.id === mission.suggested_user)?.name.split(' ')[0]} at this step.` : ''}</p>
      </section>
    </div>
  )
}
