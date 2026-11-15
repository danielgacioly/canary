// My space: one private page per astronaut. Locked, it only asks "Choose your profile".
// Inside: Health (numbers), Goals (with the patches), Suggestions (the AI slot), Trends (the charts, route
// /me/dashboard), My information and Settings (photo, PIN, lock).
import { useRef, useState, type CSSProperties } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { protocolPath } from './Protocols'
import { api } from '../api/client'
import type { CrewDetail, GoalsResponse, PersonalRecord, Suggestions } from '../api/types'
import type { Pt } from '../lib/scale'
import BloodChart from '../components/BloodChart'
import BodyView from '../components/BodyView'
import { GoalRow } from '../components/GoalItems'
import { Dot, ProfilePicker } from '../components/People'
import PinPad, { PinModal } from '../components/PinPad'
import Trend from '../components/Trend'
import { Icon, Loading, Patch, Tabs, WaitingForData } from '../components/ui'
import Check, { type CheckKind } from '../features/Checks'
import { ActionError } from '../components/Field'
import { bonePctOfPreflight, learningNote, nasaLine, num, ORIGIN } from '../lib/health'
import { squareJpeg } from '../lib/image'
import { useAction } from '../lib/useAction'
import { imageFile } from '../lib/validate'
import { useApi, useSession } from '../state/session'

type Tab = 'health' | 'goals' | 'suggestions' | 'dashboard' | 'info' | 'settings'
const TABS: [Tab, string][] = [['health', 'Health'], ['goals', 'Goals'], ['suggestions', 'Suggestions'], ['dashboard', 'Trends'], ['info', 'My information'], ['settings', 'Settings']]

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
        <div className="grow"><h1>{person.name}</h1><p className="muted">{person.role}</p></div>
      </div>
      <Tabs value={tab} options={TABS} onChange={t => nav(t === 'health' ? '/me' : `/me/${t}`)} />
      {tab === 'health' && <BodyView d={d} onCheck={setCheck} />}
      {tab === 'goals' && <GoalsTab me={me} onCheck={setCheck} />}
      {tab === 'suggestions' && <SuggestionsTab me={me} />}
      {tab === 'dashboard' && <DashboardTab d={d} me={me} />}
      {tab === 'info' && <InfoTab me={me} />}
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
  const done = data.personal.filter(g => g.done).length
  return (
    <div className="goals-page">
      <p className="goals-summary rise">
        <b>{done} of {data.personal.length}</b> done today
        {p.streak > 0 && <><span className="dot-sep" />{p.streak}-day streak</>}
      </p>
      {(['physical', 'mental'] as const).map((a, i) => {
        // A done goal keeps only its title; the order stays put so a ticked goal does not jump away.
        const list = data.personal.filter(g => g.area === a)
        const n = list.filter(g => g.done).length
        return (
          <section key={a} className="goal-group rise" style={{ ['--d' as string]: i + 1 }}>
            <div className="goal-group-head">
              <h2>{a === 'physical' ? 'Physical' : 'Mental'}</h2>
              <span className="sub">{n} of {list.length}</span>
              <span className="bar-track"><i className={`a-${a}`} style={{ width: `${(100 * n) / Math.max(1, list.length)}%` }} /></span>
            </div>
            <div className="goal-list">{list.map(g => <GoalRow key={g.id} g={g} crewId={me} onCheck={onCheck} compact={g.done} />)}</div>
          </section>
        )
      })}
      <PatchStrip p={p} />
    </div>
  )
}

/** Patches at the foot of Goals: the ones earned and the closest one to earn next. They come from habits, never from health. */
function PatchStrip({ p }: { p: GoalsResponse['profile'] }) {
  const earned = p.badges.filter(b => b.earned)
  const next = p.badges.filter(b => !b.earned).sort((a, b) => b.progress / b.need - a.progress / a.need)[0]
  const shown = next ? [...earned, next] : earned
  if (!shown.length) return null
  return (
    <section className="rise" style={{ ['--d' as string]: 3 }}>
      <div className="section-head"><h2>Patches</h2><span className="sub">{p.badges_earned} of {p.badges.length} earned</span></div>
      <div className="patches">{shown.map(b => (
        <div key={b.id} className={`patch ${b.earned ? '' : 'off'}`}>
          <Patch id={b.id} earned={b.earned} /><b>{b.name}</b>{!b.earned && <span className="small muted">Next: {b.desc.toLowerCase()}</span>}
          {!b.earned && (
            <span className="patch-progress"><span className="bar-track"><i style={{ width: `${(100 * b.progress) / b.need}%` }} /></span><span className="small dim num">{b.progress}/{b.need}</span></span>
          )}
        </div>))}</div>
    </section>
  )
}

/* ---------------------------------------------------------------- suggestions: the outside and the inside, side by side */
const TOP = 3
function SuggestionsTab({ me }: { me: string }) {
  const { bump, toast } = useSession()
  const { data, setData } = useApi<Suggestions>(() => api.suggestions(me), [me])
  const act = useAction('toast')
  if (!data) return <Loading what="suggestions" />
  const accept = (sid: string) => act.run(async () => { setData(await api.acceptSuggestion(me, sid)); bump(); toast('Added to your goals for 7 days') })
  const skip = (sid: string) => act.run(async () => { setData(await api.dismissSuggestion(me, sid)); toast('Hidden for today') })
  const card = (s: Suggestions['items'][number], i: number) => (
    <article key={s.id} className="suggest-card rise" style={{ ['--d' as string]: i + 1 }}>
      <h2 className="suggest-h"><span className={`area-dot a-${s.area === 'mental' ? 'mental' : 'physical'}`} title={s.area === 'mental' ? 'Mental' : 'Physical'} />{s.title}</h2>
      <p className="because">
        {s.because_outside && <span>{s.because_outside}</span>}
        {s.because_inside && <span className={s.because_outside ? 'muted' : ''}>{s.because_inside}</span>}
        {!s.because_outside && !s.because_inside && <span className="muted">{s.why}</span>}
        {s.protocol && <Link className="link" to={protocolPath(s.protocol)}>Protocol</Link>}
      </p>
      <ol className="steps">{s.steps.map(t => <li key={t}>{t}</li>)}</ol>
      <div className="suggest-goal">
        {s.goal && <><span className="small muted">Goal for the next 7 days</span><b>{s.goal}</b></>}
        <div className="row wrap">
          {s.goal && (s.accepted
            ? <span className="status s0"><span className="dot" />In your goals</span>
            : <button className="btn sm" onClick={() => accept(s.id)}><Icon name="plus" />Add to my goals</button>)}
          {!s.accepted && <button className="btn sm ghost" onClick={() => skip(s.id)}>Not now</button>}
        </div>
      </div>
    </article>
  )
  return (
    <div className="suggest">
      <p className="small muted rise">Picked from your own numbers and where you are. Only you see them.</p>
      <div className="suggest-list">{data.items.slice(0, TOP).map(card)}</div>
      {data.items.length > TOP && (
        <details className="suggest-more">
          <summary>{data.items.length - TOP} more</summary>
          <div className="suggest-list">{data.items.slice(TOP).map((s, i) => card(s, i))}</div>
        </details>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- dashboard: every chart in one place */
const GROUPS: [string, string[]][] = [
  ['Mental', ['sleep', 'react', 'mood', 'stress', 'social']],
  ['Physical', ['hr', 'bp', 'spo2', 'vo2', 'temp', 'gluc', 'water', 'exer', 'grip', 'bone']],
]

function DashboardTab({ d, me }: { d: CrewDetail; me: string }) {
  const { data: g } = useApi<GoalsResponse>(() => api.goals(me), [me])
  if (d.no_data) return <WaitingForData self name={d.crew.name.split(' ')[0]} />
  // A measure with no reading in the window gets no empty chart: it is named once, at the end.
  const charted = (k: string) => !!d.indicators[k] && (d.trends[k] ?? []).some(([, y]) => y !== null)
  const unread = GROUPS.flatMap(([, ids]) => ids).filter(k => d.indicators[k] && !charted(k))
  return (
    <>
      <p className="muted rise">The last 30 days, against your own normal.</p>
      {GROUPS.map(([name, all], gi) => {
        const ids = all.filter(charted)
        if (!ids.length) return null
        return (
        <section key={name} className="rise" style={{ ['--d' as string]: gi + 1 }}>
          <div className="section-head"><h2>{name}</h2></div>
          <div className="charts" style={chartCols(ids.length)}>
            {ids.map(k => {
              const i = d.indicators[k]
              const bone = k === 'bone'  // shown as % of pre-flight, like the Health tab and NASA's line
              const pts: Pt[] = bone ? d.trends[k].map(([x, y]): Pt => [x, y === null ? null : 100 + y]) : d.trends[k]
              const lim = nasaLine(k, i)
              const normal = bone ? 100 : i.baseline
              return (
                <figure key={k} className={`chart-card ${i.value === null ? 'nodata' : `s${i.level}`}`}>
                  <figcaption>
                    <span className="dot" /><b>{i.name}</b>
                    <span className="tag">{ORIGIN[i.origin]}</span>
                    <span className="num">{i.value === null ? '—' : bone ? `${num(bonePctOfPreflight(i), 1)} % of pre-flight` : `${num(i.value, i.dp)} ${i.unit}`}</span>
                  </figcaption>
                  <p className="small muted legend">
                    {normal === null ? <span>{learningNote(i) ?? 'No normal of your own yet'}</span> : <span><i className="key normal" />Your normal {bone ? '100 %' : `${num(i.baseline, i.dp)} ${i.unit}`}</span>}
                    {i.value === null && i.last_measured_day !== null && <span>Last reading day {i.last_measured_day}</span>}
                    {lim && <span><i className="key limit" />NASA limit {lim.text} <a className="item" href={lim.url} target="_blank" rel="noreferrer">source</a></span>}
                  </p>
                  <Trend pts={pts} color={name === 'Mental' ? 'var(--mental)' : 'var(--physical)'} baseline={normal ?? undefined} limit={lim?.y}
                    minSpan={bone ? 4 : i.spread * 4} avg={bone ? 7 : undefined} label={`${i.name}, last ${pts.length} days`} />
                  {i.standard && i.standard.level > 0 && <p className="small muted">{i.standard.text}</p>}
                </figure>
              )
            })}
          </div>
        </section>
        )
      })}
      {unread.length > 0 && (
        <p className="muted rise unread">
          No readings yet: {unread.map(k => d.indicators[k].name).join(', ')}.{' '}
          <Link className="link" to="/tests">Go to Tests</Link>
        </p>
      )}
      {g && <GoalsStrip days={g.profile.daily_done} />}
      <section className="rise" style={{ ['--d' as string]: 4 }}>
        <div className="section-head"><h2>Blood</h2></div>
        <BloodChart d={d} />
      </section>
    </>
  )
}

/** Columns that divide the charts evenly; whatever is left over, the last chart stretches over. */
function chartCols(count: number): CSSProperties {
  const cols = [3, 2].find(k => count % k === 0) ?? 3
  const rest = count % cols
  return { ['--cols' as string]: cols, ['--last-span' as string]: rest ? cols - rest + 1 : 1 } as CSSProperties
}

/** Goals done on each of the last 14 days: fixed-width bars. With fewer than 3 days of data, only the number. */
function GoalsStrip({ days }: { days: [number, number, number][] }) {
  const done = days.reduce((s, x) => s + x[1], 0)
  const slots = Array.from({ length: Math.max(0, 14 - days.length) }, () => null as [number, number, number] | null).concat(days.slice(-14))
  const top = Math.max(1, ...days.map(x => x[2]))
  return (
    <section className="rise" style={{ ['--d' as string]: 3 }}>
      <div className="section-head"><h2>Goals done, last 14 days</h2></div>
      {days.length < 3 ? (
        <p className="big-num">{done}<small>{done === 1 ? 'goal' : 'goals'} done</small></p>
      ) : (
        <div className="day-strip" role="img" aria-label={`${done} goals done in ${days.length} days`}>
          {slots.map((s, i) => (
            <div key={i} title={s ? `Day ${s[0]}: ${s[1]} of ${s[2]} done` : undefined}>
              <div className="bar">
                {s && <span className="num n">{s[1]}</span>}
                <i className={s ? '' : 'empty'} style={{ height: s ? Math.max(2, Math.round((84 * s[1]) / top)) : 2 }} />
              </div>
              <span className="num d">{s && (slots.length - 1 - i) % 3 === 0 ? s[0] : ''}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

/* ---------------------------------------------------------------- my information: the record Mission Control registered */
const SKIN: Record<string, string> = { I: 'Always burns, never tans', II: 'Burns easily, tans little', III: 'Sometimes burns, tans gradually', IV: 'Rarely burns, tans well', V: 'Very rarely burns', VI: 'Never burns' }
const EVA_ROLE: Record<string, string> = { surface: 'Surface EVAs', microgravity: 'Microgravity EVAs', none: 'No EVA' }
function InfoTab({ me }: { me: string }) {
  const { data: r } = useApi<PersonalRecord>(() => api.record(me), [me])
  if (!r) return <Loading what="your information" />
  const list = (x: string[]) => (x.length ? x.join(', ') : 'None')
  const dob = new Date(`${r.dob}T00:00:00`).toLocaleDateString('en-US', { day: 'numeric', month: 'long', year: 'numeric' })
  const groups: [string, [string, string][]][] = [
    ['Identity', [['Full name', r.name], ['Date of birth', dob], ['Age', `${r.age}`], ['Sex', r.sex], ['Nationality', r.nationality], ['Home', r.home], ['Languages', r.languages.join(', ')]]],
    ['Body', [['Height', `${r.height_cm} cm`], ['Weight', `${r.weight_kg} kg`], ['Body mass index', `${r.bmi}`], ['Blood type', r.blood_type], ['Skin type', `${r.skin_type} (Fitzpatrick) · ${SKIN[r.skin_type] ?? ''}`], ['Dominant hand', r.handedness], ['Vision', r.vision]]],
    ['Medical', [['Allergies', list(r.allergies)], ['Medications', list(r.medications)], ['Conditions', list(r.conditions)], ['Diet', r.diet], ['Vaccinations', r.vaccinations]]],
    ['Mission', [['Role', r.role], ['Agency', r.agency], ['Previous flights', `${r.flights}`], ['Days in space before this mission', `${r.days_in_space}`], ['EVA role', EVA_ROLE[r.eva] ?? r.eva], ['Dose from earlier flights', `${r.prior_dose.msv} mSv${r.prior_dose.estimate ? ' (estimated from days in space)' : ''}`], ['Emergency contact', r.emergency_contact]]],
  ]
  return (
    <div className="info">
      <p className="goals-summary rise">From {r.registered_by}'s records<span className="dot-sep" />Only you and the medical team see it<span className="dot-sep" />To correct something, tell the flight surgeon</p>
      <div className="info-grid">
        {groups.map(([title, rows], i) => (
          <section key={title} className="info-group rise" style={{ ['--d' as string]: i + 1 }}>
            <h2>{title}</h2>
            <dl>{rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd className={k === 'Blood type' ? 'big' : ''}>{v}</dd></div>)}</dl>
          </section>
        ))}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- settings: photo, PIN, lock */
function SettingsTab({ d, me }: { d: CrewDetail; me: string }) {
  const { setMe, bump, toast, photos } = useSession()
  const nav = useNavigate()
  const file = useRef<HTMLInputElement>(null)
  const [pinOpen, setPinOpen] = useState(false)
  const first = d.crew.name.split(' ')[0]
  const photo = useAction()
  const [photoErr, setPhotoErr] = useState<string | null>(null)
  const pick = async (f: File | undefined) => {
    if (!f) return
    const bad = imageFile(f)  // PNG, JPEG or WebP, at most 8 MB: said under the buttons, not in a toast
    setPhotoErr(bad)
    if (bad) return
    await photo.run(async () => {
      let url: string
      try { url = await squareJpeg(f, 256) } catch { throw new Error('That file could not be read as an image. Pick another photo.') }
      await api.setPhoto(me, url)
      bump(); toast('Photo updated')
    })
  }
  return (
    <div className="settings">
      <section className="set-group rise">
        <h2>Profile photo</h2>
        <div className="set-row">
          <Dot p={d.crew} size="lg" />
          <div className="grow"><b>Shown to the crew</b><p className="small muted">On the crew page and in the top bar. Nothing else about you is.</p></div>
          <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={e => { pick(e.target.files?.[0]); e.target.value = '' }} />
          <button className="btn" disabled={photo.busy} onClick={() => file.current?.click()}>{photo.busy ? 'Saving…' : photos[me] ? 'Change photo' : 'Add photo'}</button>
          {photos[me] && <button className="btn ghost" disabled={photo.busy} onClick={() => { setPhotoErr(null); photo.run(async () => { await api.deletePhoto(me); bump() }) }}>Remove</button>}
        </div>
        <ActionError error={photoErr ?? photo.error} />
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
          <div className="grow"><b>Who sees your health</b><p className="small muted">Only you and the medical team. The crew sees your goals done and your photo. Your alerts go to {d.care_by}.</p></div>
        </div>
      </section>
      {pinOpen && <ChangePin me={me} first={first} onClose={() => setPinOpen(false)} onDone={() => { setPinOpen(false); toast('PIN changed. Use the new one next time.') }} />}
    </div>
  )
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
      <span className="lbl pin-step">Change PIN, step {stepNo} of 3</span>
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
