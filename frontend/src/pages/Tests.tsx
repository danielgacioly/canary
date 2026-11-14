// Tests: any self-test or log, any time. Choose your profile, enter the PIN, pick a test.
// Results go to your health (and the medical team), never to the crew.
import { useState } from 'react'
import { api } from '../api/client'
import type { TestDef, TestHistory } from '../api/types'
import { GuideBody } from '../components/BodyView'
import { Dot, ProfilePicker } from '../components/People'
import { Loading } from '../components/ui'
import { useAction } from '../lib/useAction'
import Check, { type CheckKind } from '../features/Checks'
import { ActionError } from '../components/Field'
import { useApi, useSession } from '../state/session'

const GROUP_NOTE: Record<string, string> = {
  Cognition: 'Short tasks of the kind NASA uses on the ISS. Do them at the same time of day so they compare.',
  'How you feel': 'Validated questionnaires, a minute each. A hard day counts the same as a good one.',
  Body: 'What sensors cannot see on their own.',
  Logs: 'Habits that help read the numbers.',
}

/** Tests whose measurement is an indicator in the team's guide. The others (PVT, DSST, KSS, TLX, PHQ-2/GAD-2, Amsler, journal, reading, symptoms)
 *  have no guide entry: they show their own one-line measure and source, nothing more. */
const GUIDE_OF: Record<string, string[]> = { vitals: ['bp', 'hr', 'temp', 'spo2'], sleep: ['sleep'], mood: ['mood'] }

export default function Tests() {
  const { me } = useSession()
  if (!me) return <ProfilePicker title="Choose your profile to run tests" />
  return <Run me={me} />
}

function Run({ me }: { me: string }) {
  const { catalog } = useSession()
  const { data } = useApi<TestHistory>(() => api.checkins(me), [me])
  const [open, setOpen] = useState<CheckKind | null>(null)
  const [photo, setPhoto] = useState<{ id: number; url: string } | null>(null)
  const load = useAction()
  const person = catalog?.crew.find(c => c.id === me)
  if (!data || !person) return <Loading what="tests" />
  const groups = [...new Set(data.tests.map(t => t.group))]
  const doneToday = data.recent.filter(r => r.day === data.recent[0]?.day).length

  return (
    <div className="page tests">
      <div className="space-head rise">
        <Dot p={person} size="md" />
        <div className="grow">
          <h1>Tests</h1>
          <p className="muted">{person.name} · {data.tests.length} tests and logs · results are private to you and the medical team</p>
        </div>
      </div>

      {groups.map((g, gi) => (
        <section key={g} className="rise" style={{ ['--d' as string]: gi + 1 }}>
          <div className="section-head"><h2>{g}</h2><span className="sub">{GROUP_NOTE[g]}</span></div>
          <div className="test-list">
            {data.tests.filter(t => t.group === g).map(t => <TestRow key={t.id} t={t} onStart={() => setOpen(t.id as CheckKind)} />)}
          </div>
        </section>
      ))}

      {!!data.recent.length && (
        <section className="rise" style={{ ['--d' as string]: 6 }}>
          <div className="section-head"><h2>Recent results</h2><span className="sub">{doneToday} on day {data.recent[0].day}</span></div>
          <ul className="plain recent">
            {data.recent.slice(0, 8).map((r, i) => (
              <li key={i}><b>{data.tests.find(t => t.id === r.kind)?.name ?? r.kind}</b><span className="muted">{r.summary}</span>
                <span className="dim small num">day {r.day}{r.has_photo && <> · <button type="button" className="link-btn" disabled={load.busy} onClick={() => photo?.id === r.id ? setPhoto(null) : load.run(async () => setPhoto({ id: r.id, url: (await api.checkinPhoto(me, r.id)).data_url }))}>{photo?.id === r.id ? 'Hide photo' : 'Photo'}</button></>}</span>
                {photo?.id === r.id && <img className="recent-photo" src={photo.url} alt={`Photo of the display kept with the vital signs of day ${r.day}`} />}
              </li>
            ))}
          </ul>
          <ActionError error={load.error} />
        </section>
      )}
      {open && <Check kind={open} onClose={() => setOpen(null)} />}
    </div>
  )
}

function TestRow({ t, onStart }: { t: TestDef; onStart: () => void }) {
  const { catalog } = useSession()
  const mins = t.minutes < 1 ? `${Math.round(t.minutes * 60)} s` : `${t.minutes} min`
  const entries = (GUIDE_OF[t.id] ?? []).filter(k => catalog?.guide?.[k])
  return (
    <div className="test-item">
      <div className="test-row">
        <span className="grow">
          <b>{t.name}</b>
          <span className="small muted">{t.measures}</span>
          <span className="small dim">{t.source}</span>
        </span>
        <span className="test-last">
          {t.latest ? <><span className="small">{t.latest.summary}</span><span className="small dim num">day {t.latest.day}</span></> : <span className="small dim">Not done yet</span>}
        </span>
        <span className="test-go"><span className="small dim num">{mins}</span><button className="btn sm" onClick={onStart} aria-label={`Start ${t.name}, ${mins}`}>Start</button></span>
      </div>
      {entries.length > 0 && (
        <details className="how">
          <summary>How and why</summary>
          {entries.map(k => (
            <div key={k} className="how-one">
              {entries.length > 1 && <b>{catalog!.indicators[k]?.name ?? k}</b>}
              <GuideBody g={catalog!.guide![k]} />
            </div>
          ))}
        </details>
      )}
    </div>
  )
}
