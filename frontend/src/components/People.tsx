// People as dots. Crew-facing dots are neutral: nobody's operational status is shown to the crew.
// A dot shows the person's photo when they set one, otherwise their initials.
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Ops } from '../api/types'
import { useSession } from '../state/session'
import PinPad, { PinModal } from './PinPad'
import { Icon } from './ui'

/** The demo PINs, mirroring the backend defaults (CANARY_CREW_PINS). Shown only as a hint in the demo. */
export const DEMO_PINS: Record<string, string> = { h: '1001', k: '1002', a: '1003', t: '1004' }

interface DotPerson { id?: string; initials: string; name: string }

/** A person as a dot. Neutral unless `ops` is given, which only private views do. */
export function Dot({ p, ops, size = 'md', me = false, title }: { p: DotPerson; ops?: Ops; size?: 'sm' | 'md' | 'lg' | 'xl'; me?: boolean; title?: string }) {
  const { photos } = useSession()
  const photo = p.id ? photos[p.id] : undefined
  return (
    <span className={`pdot ${size} ${ops ? `s${ops.level}` : 'neutral'} ${me ? 'me' : ''} ${photo ? 'has-photo' : ''}`} title={title ?? (ops ? `${p.name}: ${ops.label}` : p.name)}>
      {photo ? <img src={photo} alt="" /> : <span className="ini">{p.initials}</span>}
      {ops && <i />}
    </span>
  )
}

/** The crew in the top bar: tap a dot to open that person. */
export function CrewDots({ people }: { people: DotPerson[] }) {
  const { me } = useSession()
  const nav = useNavigate()
  return (
    <div className="crewdots" role="group" aria-label="Crew">
      {people.map(p => (
        <button key={p.id} onClick={() => nav(p.id === me ? '/me' : `/crew/${p.id}`)} aria-label={p.name}>
          <Dot p={p} size="sm" me={p.id === me} />
        </button>
      ))}
    </div>
  )
}

/** The locked state of My space: pick a profile, then the PIN. Nothing else on screen. */
export function ProfilePicker({ preselect = null, title = 'Choose your profile' }: { preselect?: string | null; title?: string }) {
  const { catalog, setMe } = useSession()
  const [, setParams] = useSearchParams()
  const [who, setWho] = useState<string | null>(preselect)
  if (!catalog) return null
  const person = catalog.crew.find(c => c.id === who)
  const close = () => { setWho(null); setParams({}, { replace: true }) }
  return (
    <div className="page picker">
      <span className="lock rise"><Icon name="lock" size={22} /></span>
      <h1 className="rise">{title}</h1>
      <div className="picker-grid">
        {catalog.crew.map((c, i) => (
          <button key={c.id} className="rise" style={{ ['--d' as string]: i + 1 }} onClick={() => setWho(c.id)}>
            <Dot p={c} size="lg" />
            <b>{c.name}</b>
            <span className="small muted">{c.role}</span>
          </button>
        ))}
      </div>
      {person && (
        <PinModal onCancel={close}>
          <PinPad key={person.id} title={`Hello, ${person.name.split(' ')[0]}`} subtitle="Enter your 4-digit PIN" hint={DEMO_PINS[person.id] ? `Demo PIN: ${DEMO_PINS[person.id]}` : undefined} onCancel={close}
            onSubmit={async pin => { await api.crewSignIn(person.id, pin); setMe(person.id); setParams({}, { replace: true }) }} />
        </PinModal>
      )}
    </div>
  )
}
