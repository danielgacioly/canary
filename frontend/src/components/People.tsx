// People as dots. Crew-facing dots are neutral: nobody's operational status is shown to the crew.
// Status colour appears only where the viewer may see it (your own space, the medical console).
// Health details live behind each astronaut's own PIN (see EnterGate).
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Ops, Person } from '../api/types'
import { useSession } from '../state/session'
import PinPad, { PinModal } from './PinPad'
import { Icon } from './ui'

/** The demo PINs, mirroring the backend defaults (CANARY_CREW_PINS). Shown only as a hint in the demo. */
export const DEMO_PINS: Record<string, string> = { h: '1001', k: '1002', a: '1003', t: '1004' }

/** A person as a dot. Neutral (no status ring, pip or halo) unless `ops` is given, which only private views do. */
export function Dot({ p, ops, size = 'md', me = false, title }: { p: Pick<Person, 'initials' | 'name'>; ops?: Ops; size?: 'sm' | 'md' | 'xl'; me?: boolean; title?: string }) {
  return (
    <span className={`pdot ${size} ${ops ? `s${ops.level}` : 'neutral'} ${me ? 'me' : ''}`} title={title ?? (ops ? `${p.name}: ${ops.label}` : p.name)}>
      <span className="ini">{p.initials}</span>
      {ops && <i />}
    </span>
  )
}

/** The crew in the top bar: tap a dot to open that person. */
export function CrewDots({ people }: { people: Person[] }) {
  const { me } = useSession()
  const nav = useNavigate()
  return (
    <div className="crewdots" role="group" aria-label="Crew">
      {people.map(p => (
        <button key={p.id} onClick={() => nav(p.id === me ? '/today' : `/crew/${p.id}`)} aria-label={p.name}>
          <Dot p={p} size="sm" me={p.id === me} />
        </button>
      ))}
    </div>
  )
}

/** Shown wherever personal data would appear and nobody has entered their space. Tapping a name asks for the PIN. */
export function EnterGate({ what = 'your health', preselect = null }: { what?: string; preselect?: string | null }) {
  const { catalog, setMe, mission } = useSession()
  const [, setParams] = useSearchParams()
  const [who, setWho] = useState<string | null>(preselect && DEMO_PINS[preselect] ? preselect : null)
  if (!catalog) return null
  const person = catalog.crew.find(c => c.id === who)
  const close = () => { setWho(null); setParams({}, { replace: true }) }
  return (
    <div className="page">
      <section className="gate detail-card rise">
        <span className="lock"><Icon name="lock" size={22} /></span>
        <span className="eyebrow">Private space</span>
        <h1>Enter to see {what}.</h1>
        <p className="muted">Your numbers, alerts, advice and operational status are yours. The crew sees only whether you kept your routine. Only you and the medical team see the rest, unless you choose to share your data.</p>
        <div className="gate-people">
          {catalog.crew.map((c, i) => (
            <button key={c.id} className="rise" style={{ ['--d' as string]: i + 1 }} onClick={() => setWho(c.id)}>
              <span className={`pdot md neutral ${mission?.suggested_user === c.id ? 'me' : ''}`}><span className="ini">{c.initials}</span></span>
              <b>{c.name.split(' ')[0]}</b><span className="small muted">{c.role}</span>
            </button>
          ))}
        </div>
        <p className="small dim">Tap your name and enter your 4-digit PIN. Closing this window locks your space again.{mission ? ` The demo story is following ${catalog.crew.find(c => c.id === mission.suggested_user)?.name.split(' ')[0]} at this step.` : ''}</p>
      </section>
      {person && (
        <PinModal onCancel={close}>
          <PinPad key={person.id} title={`Hello, ${person.name.split(' ')[0]}`} subtitle="Enter your 4-digit PIN" hint={`Demo PIN: ${DEMO_PINS[person.id]}`} onCancel={close}
            onSubmit={async pin => { await api.crewSignIn(person.id, pin); setMe(person.id); setParams({}, { replace: true }) }} />
        </PinModal>
      )}
    </div>
  )
}
