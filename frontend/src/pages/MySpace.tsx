// My space: one private page per astronaut. Locked, it only asks "Choose your profile".
// Inside: Health (numbers), Goals, Suggestions (the AI slot), Patches, Dashboard (the charts)
// and Settings (photo, PIN, lock).
import { useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { CrewDetail, GoalsResponse, Suggestions } from '../api/types'
import BodyView, { Blood } from '../components/BodyView'
import { GoalRow, TeamRow } from '../components/GoalItems'
import { Dot, ProfilePicker } from '../components/People'
import PinPad, { PinModal } from '../components/PinPad'
import { Icon, LineChart, Loading, Patch, Tabs } from '../components/ui'
import Check, { type CheckKind } from '../features/Checks'
import { useApi, useSession } from '../state/session'

type Tab = 'health' | 'goals' | 'suggestions' | 'patches' | 'dashboard' | 'settings'
const TABS: [Tab, string][] = [['health', 'Health'], ['goals', 'Goals'], ['suggestions', 'Suggestions'], ['patches', 'Patches'], ['dashboard', 'Dashboard'], ['settings', 'Settings']]

export default function MySpace() {
  const { me } = useSession()
  const [params] = useSearchParams()
  const who = params.get('who')  // the demo bar's "Enter as ..." lands here: still asks for that person's PIN
  if (!me || (who && who !== me)) return <ProfilePicker preselect={who} />
  return <Inside me={me} />
}

function Inside({ me }: { me: string }) {
  const { tab: raw } = useParams()
  const tab: Tab = TABS.some(([k]) => k === raw) ? (raw as Tab) : 'health'
  const nav = useNavigate()
  const { catalog } = useSession()
  const { data: d, error } = useApi(() => api.crewDetail(me), [me])
  const [check, setCheck] = useState<CheckKind | null>(null)
  const person = catalog?.crew.find(c => c.id === me)
  if (error) return <div className="page"><p className="muted">Cannot reach the Canary API. Is the backend running on port 8000?</p></div>
  if (!d || !person) return <Loading what="your space" />
  return (
    <div className="page myspace">
      <div className="space-head rise">
        <Dot p={person} size="md" />
        <div className="grow"><h1>{person.name}</h1><p className="muted">{person.role} · {d.mission.day_label} · {d.mission.place.name}</p></div>
      </div>
      <Tabs value={tab} options={TABS} onChange={t => nav(t === 'health' ? '/me' : `/me/${t}`)} />
      {tab === 'health' && <BodyView d={d} onCheck={setCheck} />}
      {tab === 'goals' && <GoalsTab me={me} onCheck={setCheck} />}
      {tab === 'suggestions' && <SuggestionsTab me={me} />}
      {tab === 'patches' && <PatchesTab me={me} />}
      {tab === 'dashboard' && <DashboardTab d={d} me={me} />}
      {tab === 'settings' && <SettingsTab d={d} me={me} />}
      {check && <Check kind={check} onClose={() => setCheck(null)} />}
    </div>
  )
}

/* ---------------------------------------------------------------- goals: one area at a time, room to breathe */
function GoalsTab({ me, onCheck }: { me: string; onCheck: (k: CheckKind) => void }) {
  const { catalog } = useSession()
  const { data } = useApi<GoalsResponse>(() => api.goals(me), [me])
  if (!data || !catalog) return <Loading what="goals" />
  const p = data.profile
  const names = Object.fromEntries(catalog.crew.map(c => [c.id, c.name]))
  const done = data.personal.filter(g => g.done).length
  return (
    <div className="goals-page">
      <p className="goals-summary rise">
        <b>{done} of {data.personal.length}</b> done today
        <span className="dot-sep" />{p.streak}-day streak
        <span className="dot-sep" />{p.completion_7d}% over the last 7 days
      </p>
      {(['physical', 'mental'] as const).map((a, i) => {
        const list = data.personal.filter(g => g.area === a)
        const n = list.filter(g => g.done).length
        return (
          <section key={a} className="goal-group rise" style={{ ['--d' as string]: i + 1 }}>
            <div className="goal-group-head">
              <h2>{a === 'physical' ? 'Physical' : 'Mental'}</h2>
              <span className="sub">{n} of {list.length}</span>
              <span className="bar-track"><i style={{ width: `${(100 * n) / Math.max(1, list.length)}%`, background: a === 'physical' ? 'var(--physical)' : 'var(--mental)' }} /></span>
            </div>
            <div className="goal-list">{list.map(g => <GoalRow key={g.id} g={g} crewId={me} onCheck={onCheck} />)}</div>
          </section>
        )
      })}
      <section className="rise" style={{ ['--d' as string]: 3 }}>
        <div className="section-head"><h2>Crew missions this week</h2><span className="sub">Shared goals for the whole crew</span></div>
        <div className="team-grid">{data.team.map(t => <TeamRow key={t.id} t={t} names={names} />)}</div>
      </section>
    </div>
  )
}

/* ---------------------------------------------------------------- suggestions: the AI slot, fed by your own data */
function SuggestionsTab({ me }: { me: string }) {
  const { bump, toast } = useSession()
  const { data, setData } = useApi<Suggestions>(() => api.suggestions(me), [me])
  if (!data) return <Loading what="suggestions" />
  const accept = async (sid: string) => { setData(await api.acceptSuggestion(me, sid)); bump(); toast('Added to your goals for 7 days') }
  return (
    <div className="suggest">
      <div className="slot-line rise">
        <span className="tag">{data.mode === 'ai' ? `AI · ${data.provider}` : 'AI slot · no model connected'}</span>
        <span className="small muted">Built from your numbers against your own normal, your goals this week, your tests and the next leg of the plan. {data.mode === 'ai' ? 'A model rephrased them; every number was checked.' : 'Until a model is connected, rules write them from the same data.'} Only you see them.</span>
      </div>
      <div className="suggest-list">
        {data.items.map((s, i) => (
          <article key={s.id} className="suggest-card rise" style={{ ['--d' as string]: i + 1 }}>
            <div className="row" style={{ gap: 10 }}>
              <span className="area-dot" style={{ background: s.area === 'mental' ? 'var(--mental)' : 'var(--physical)' }} />
              <span className="small muted">{s.area === 'mental' ? 'Mental' : 'Physical'}</span>
            </div>
            <h2>{s.title}</h2>
            <p className="muted">{s.why}</p>
            <ol className="steps">{s.steps.map(t => <li key={t}>{t}</li>)}</ol>
            {s.goal && (
              <div className="suggest-goal">
                <span className="small muted">Goal for the next 7 days</span>
                <b>{s.goal}</b>
                {s.accepted
                  ? <span className="status s0"><span className="dot" />In your goals</span>
                  : <button className="btn sm" onClick={() => accept(s.id)}><Icon name="plus" />Add to my goals</button>}
              </div>
            )}
          </article>
        ))}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- patches: their own page */
function PatchesTab({ me }: { me: string }) {
  const { data } = useApi<GoalsResponse>(() => api.goals(me), [me])
  if (!data) return <Loading what="patches" />
  const p = data.profile
  return (
    <div className="col" style={{ gap: 24 }}>
      <p className="goals-summary rise"><b>{p.badges_earned} of {p.badges.length}</b> patches earned<span className="dot-sep" />They come from habits kept over time, never from health numbers</p>
      <div className="patches big">{p.badges.map((b, i) => (
        <div key={b.id} className={`patch rise ${b.earned ? '' : 'off'}`} style={{ ['--d' as string]: i }}>
          <Patch id={b.id} earned={b.earned} /><b>{b.name}</b><span className="small muted">{b.desc}</span>
          {b.earned ? <span className="small" style={{ color: 'var(--gold)' }}>Earned</span> : (
            <span className="patch-progress"><span className="bar-track"><i style={{ width: `${(100 * b.progress) / b.need}%` }} /></span><span className="small dim num">{b.progress}/{b.need}</span></span>
          )}
        </div>))}</div>
    </div>
  )
}

/* ---------------------------------------------------------------- dashboard: every chart in one place */
function DashboardTab({ d, me }: { d: CrewDetail; me: string }) {
  const { data: g } = useApi<GoalsResponse>(() => api.goals(me), [me])
  const groups: [string, string[]][] = [
    ['Mental', ['sleep', 'react', 'mood', 'stress', 'social']],
    ['Physical', ['hr', 'bp', 'spo2', 'temp', 'gluc', 'water', 'exer', 'grip', 'bone']],
  ]
  return (
    <>
      <p className="muted rise">Last 30 days against your own normal (dashed line). Readings are simulated in this prototype; the blood counts are real NASA data.</p>
      {groups.map(([name, ids], gi) => (
        <section key={name} className="rise" style={{ ['--d' as string]: gi + 1 }}>
          <div className="section-head"><h2>{name}</h2></div>
          <div className="charts">
            {ids.filter(k => d.indicators[k]).map(k => {
              const i = d.indicators[k]
              return (
                <figure key={k} className={`chart-card s${i.level}`}>
                  <figcaption><span className="dot" /><b>{i.name}</b><span className="num muted">{i.value.toFixed(i.dp)} {i.unit}</span></figcaption>
                  <LineChart series={[{ pts: d.trends[k], color: name === 'Mental' ? 'var(--mental)' : 'var(--physical)' }]} refY={i.baseline} refLabel="your normal" w={360} h={150} />
                </figure>
              )
            })}
          </div>
        </section>
      ))}
      {g && (
        <section className="rise" style={{ ['--d' as string]: 3 }}>
          <div className="section-head"><h2>Goals done, last 14 days</h2></div>
          <div className="day-bars">
            {g.profile.daily_done.map(([day, n, total]) => (
              <div key={day} title={`Day ${day}: ${n} done`}><i style={{ height: `${Math.min(100, (100 * n) / Math.max(1, total))}%` }} /><span className="num">{day}</span></div>
            ))}
          </div>
        </section>
      )}
      <section className="rise" style={{ ['--d' as string]: 4 }}>
        <div className="section-head"><h2>Blood</h2><span className="sub">Lymphocytes from NASA OSD-569 (Inspiration4), the first cells to drop after radiation</span></div>
        <div style={{ maxWidth: 560 }}><Blood d={d} /></div>
      </section>
    </>
  )
}

/* ---------------------------------------------------------------- settings: photo, PIN, lock */
function SettingsTab({ d, me }: { d: CrewDetail; me: string }) {
  const { setMe, bump, toast, photos } = useSession()
  const nav = useNavigate()
  const file = useRef<HTMLInputElement>(null)
  const [pinOpen, setPinOpen] = useState(false)
  const first = d.crew.name.split(' ')[0]
  const pick = async (f: File | undefined) => {
    if (!f) return
    try {
      await api.setPhoto(me, await squareJpeg(f, 256))
      bump(); toast('Photo updated')
    } catch (e) { toast(`Could not use that image: ${(e as Error).message}`) }
  }
  return (
    <div className="settings">
      <section className="set-group rise">
        <h2>Profile photo</h2>
        <div className="set-row">
          <Dot p={d.crew} size="lg" />
          <div className="grow"><b>Shown to the crew</b><p className="small muted">Like a name badge: it appears on the crew page and in the top bar. Nothing else about you does.</p></div>
          <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={e => { pick(e.target.files?.[0]); e.target.value = '' }} />
          <button className="btn" onClick={() => file.current?.click()}>{photos[me] ? 'Change photo' : 'Add photo'}</button>
          {photos[me] && <button className="btn ghost" onClick={async () => { await api.deletePhoto(me); bump() }}>Remove</button>}
        </div>
      </section>
      <section className="set-group rise" style={{ ['--d' as string]: 1 }}>
        <h2>Security</h2>
        <div className="set-row">
          <div className="grow"><b>PIN</b><p className="small muted">Four digits that open your space on any terminal.</p></div>
          <button className="btn" onClick={() => setPinOpen(true)}>Change PIN</button>
        </div>
        <div className="set-row">
          <div className="grow"><b>Lock my space</b><p className="small muted">Closing this window also locks it.</p></div>
          <button className="btn" onClick={() => { setMe(null); nav('/crew') }}><Icon name="lock" />Lock</button>
        </div>
      </section>
      <section className="set-group rise" style={{ ['--d' as string]: 2 }}>
        <h2>Privacy</h2>
        <div className="set-row">
          <div className="grow"><b>Who sees your health</b><p className="small muted">Only you and the medical team. The crew sees your goal participation and your photo. Your alerts go to {d.care_by}.</p></div>
        </div>
      </section>
      {pinOpen && <ChangePin me={me} first={first} onClose={() => setPinOpen(false)} onDone={() => { setPinOpen(false); toast('PIN changed. Use the new one next time.') }} />}
    </div>
  )
}

/** Center-crop and shrink an image to a small JPEG data URL. */
function squareJpeg(f: File, size: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    const url = URL.createObjectURL(f)
    img.onload = () => {
      const s = Math.min(img.width, img.height)
      const c = document.createElement('canvas')
      c.width = c.height = size
      c.getContext('2d')!.drawImage(img, (img.width - s) / 2, (img.height - s) / 2, s, s, 0, 0, size, size)
      URL.revokeObjectURL(url)
      resolve(c.toDataURL('image/jpeg', 0.85))
    }
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('not an image')) }
    img.src = url
  })
}

/** Three pads in a row: the current PIN (checked by the server), a new one, the new one again. */
function ChangePin({ me, first, onClose, onDone }: { me: string; first: string; onClose: () => void; onDone: () => void }) {
  const [step, setStep] = useState<'current' | 'new' | 'confirm'>('current')
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [mismatch, setMismatch] = useState(false)
  const stepNo = { current: 1, new: 2, confirm: 3 }[step]
  return (
    <PinModal onCancel={onClose}>
      <span className="lbl" style={{ display: 'block', textAlign: 'center', marginBottom: 8 }}>Change PIN, step {stepNo} of 3</span>
      {step === 'current' && <PinPad key="c" title="Current PIN" subtitle={`${first}, enter the PIN you use now`} onCancel={onClose}
        onSubmit={async pin => { await api.crewSignIn(me, pin); setCurrent(pin); setStep('new') }} />}
      {step === 'new' && <PinPad key="n" title="New PIN" subtitle={mismatch ? 'The two did not match. Choose again.' : 'Choose 4 digits you will remember'} onCancel={onClose}
        onSubmit={async pin => { if (pin === current) throw new Error('Pick a different PIN from the current one.'); setNext(pin); setMismatch(false); setStep('confirm') }} />}
      {step === 'confirm' && <PinPad key="m" title="Confirm new PIN" subtitle="Enter the new PIN once more" onCancel={onClose}
        onSubmit={async pin => {
          if (pin !== next) { setMismatch(true); setStep('new'); return }
          await api.changePin(me, current, pin)
          onDone()
        }} />}
    </PinModal>
  )
}
