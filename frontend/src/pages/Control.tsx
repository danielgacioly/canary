// Canary Control: the Mission Control side of the system, in its own mode.
// It registers the crew and the mission (no accounts on board), follows each person the way
// Earth may (operational status as the ship's medical team reports it, participation, hazards),
// and exchanges delayed messages with the ship's medical console.
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { ControlOverview, MissionForm, SeatForm } from '../api/types'
import Timeline from '../components/Timeline'
import { ActionError, Field, FormError, FormSummary, SubmitButton } from '../components/Field'
import { Dot } from '../components/People'
import Hazards from '../components/Hazards'
import PinPad from '../components/PinPad'
import Stars from '../components/Stars'
import { CanaryMark, Icon, Loading, Tabs } from '../components/ui'
import { useAction } from '../lib/useAction'
import { useForm, type Errors } from '../lib/useForm'
import * as v from '../lib/validate'
import { clockLine } from '../lib/clock'
import { useProtocolName } from '../lib/names'
import { useApi, useSession } from '../state/session'
import ControlData from './ControlData'

type Tab = 'dashboard' | 'register' | 'data' | 'messages'
const MAX_PEOPLE = 6
const BLOOD = ['O−', 'O+', 'A−', 'A+', 'B−', 'B+', 'AB−', 'AB+']
const SKIN = ['I', 'II', 'III', 'IV', 'V', 'VI']
const SEX = ['Female', 'Male', 'Other']
const HAND = ['Right', 'Left']
const EVA: [string, string][] = [['surface', 'Surface EVAs'], ['microgravity', 'Microgravity EVAs'], ['none', 'No EVA']]

const emptySeat = (seat = ''): SeatForm => ({
  seat, name: '', role: '', home: '', pin: '', dob: '1990-01-01', sex: '', nationality: '', languages: [], agency: '', flights: 0,
  days_in_space: 0, height_cm: 170, weight_kg: 70, blood_type: '', skin_type: 'III', handedness: 'Right', vision: '', allergies: [],
  medications: [], conditions: [], diet: '', vaccinations: '', emergency_contact: '', eva: 'surface', prior_dose_msv: null,
})
const emptyMission: MissionForm = { callsign: '', name: '', launch_date: '2035-06-01', preset: 'mars', rover: true }

export default function Control() {
  const [signed, setSigned] = useState(api.isControl())
  if (!signed) return <ControlGate onOk={() => setSigned(true)} />
  return <ControlApp onSignOut={() => { api.controlSignOut(); setSigned(false) }} />
}

function ControlGate({ onOk }: { onOk: () => void }) {
  const nav = useNavigate()
  return (
    <div className="control control-gate">
      <Stars />
      <div className="row control-top"><span className="brand"><CanaryMark size={22} />CANARY CONTROL</span>
        <button className="btn sm ghost right" onClick={() => nav('/crew')}><Icon name="back" />Back to the crew view</button></div>
      <div className="control-gate-body">
        <p className="muted reveal lock-note">Mission Control's side of Canary: register the crew and the mission, follow each person the way Earth may, and talk to the ship's medical team.</p>
        <PinPad title="Mission Control" subtitle="Enter the 4-digit Mission Control PIN" hint="PIN: 4242" onSubmit={async pin => { await api.controlSignIn(pin); onOk() }} />
      </div>
    </div>
  )
}

function ControlApp({ onSignOut }: { onSignOut: () => void }) {
  const nav = useNavigate()
  const { bump, rev } = useSession()
  const [ov, setOv] = useState<ControlOverview | null>(null)
  const [tab, setTab] = useState<Tab | null>(null)
  useEffect(() => { api.controlOverview().then(o => { setOv(o); setTab(t => t ?? (o.registered ? 'dashboard' : 'register')) }).catch(onSignOut) }, [rev, onSignOut])
  if (!ov || !tab) return <div className="control"><Loading what="Canary Control" /></div>
  const refresh = (o: ControlOverview) => { setOv(o); bump() }
  const loadDemoData = async () => { refresh(await api.controlDemoData()); setTab('dashboard') }
  return (
    <div className="control">
      <header className="control-top">
        <span className="brand"><CanaryMark size={22} />CANARY CONTROL</span>
        <span className="small muted">{ov.registered ? `${ov.overview.callsign} · ${ov.mission.day_label} · ${clockLine(ov.mission.clock)} · ${ov.mission.place.name}` : 'No mission registered'}</span>
        <div className="right row" style={{ gap: 8 }}>
          <button className="btn sm" onClick={() => nav('/crew')}><Icon name="back" />Back to the crew view</button>
          <button className="btn sm ghost" onClick={onSignOut}>Sign out</button>
        </div>
      </header>
      <div className="control-page">
        <Tabs value={tab} onChange={setTab} options={[['dashboard', 'Dashboard'], ['register', 'Register crew and mission'], ['data', 'Data'], ['messages', 'Messages']]} />
        {tab === 'dashboard' && <Dashboard ov={ov} onClear={async () => { refresh(await api.controlClear()); setTab('register') }}
          onDemo={loadDemoData} onRegister={() => setTab('register')} />}
        {tab === 'register' && <Register registered={ov.registered} onSaved={o => { refresh(o); setTab('dashboard') }} onDemo={loadDemoData} />}
        {tab === 'data' && <ControlData />}
        {tab === 'messages' && <ControlMessages delay={ov.mission.place.reply} />}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- dashboard */
function Dashboard({ ov, onClear, onDemo, onRegister }: { ov: ControlOverview; onClear: () => Promise<void>; onDemo: () => Promise<void>; onRegister: () => void }) {
  const [confirm, setConfirm] = useState<'clear' | 'demo' | null>(null)
  const clear = useAction()
  const demo = useAction()
  const protocol = useProtocolName()
  if (!ov.registered) {
    return (
      <div className="empty-ctl rise">
        <h2>Nothing registered</h2>
        <p className="muted">The crew terminals are waiting. Register the crew (one to six people) and the mission, or fill everything with the demo mission.</p>
        <div className="row" style={{ gap: 8, justifyContent: 'center' }}>
          <button className="btn pri" onClick={onRegister}>Register crew and mission</button>
          <button className="btn" disabled={demo.busy} onClick={() => demo.run(onDemo)}>{demo.busy ? 'Loading…' : 'Use demo data'}</button>
        </div>
        <ActionError error={demo.error} />
      </div>
    )
  }
  const ms = ov.mission
  return (
    <>
      <div className="stats rise">
        <div className="stat"><div className="k">Mission</div><b>{ov.overview.callsign}</b><div className="s">{ov.overview.name}</div></div>
        <div className="stat"><div className="k">Mission time</div><b>{ms.day_label}</b><div className="s">{ms.leg.label || ms.place.name}</div></div>
        <div className="stat"><div className="k">Signal delay</div><b>{ms.place.reply}</b><div className="s">each way</div></div>
        <div className="stat"><div className="k">Mission dose</div><b>{ov.dose.mission_msv} mSv</b><div className="s">{ov.dose.pct_of_limit}% of the career limit</div></div>
      </div>

      <section className="rise" style={{ ['--d' as string]: 1 }}>
        <div className="section-head"><h2>Crew</h2><span className="sub">Operational status as the ship's medical team reports it. Health details stay on board.</span></div>
        <div className="ctl-crew">
          {ov.people.map(p => (
            <div key={p.id} className="ctl-person">
              <Dot p={p} ops={p.ops} size="md" />
              <div className="col" style={{ gap: 2 }}><b>{p.name}</b><span className="small muted">{p.role}</span></div>
              <span className={`status s${p.ops.level}`}><span className="dot" />{p.ops.label}</span>
              <span className="small muted">{p.today ? `${p.today.done} of ${p.today.total} goals today · ${p.today.streak}-day streak` : '—'}</span>
              <span className="small dim">{p.last_checkin_day !== null ? `Last self-test: day ${p.last_checkin_day}` : 'No self-tests yet'}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="rise" style={{ ['--d' as string]: 2 }}>
        <div className="section-head"><h2>Hazards at {ms.place.name}</h2></div>
        {ov.warnings.map(w => <div key={w.title} className="warning s2"><span className="dot" /><div className="grow"><b>{w.title}</b><p className="small muted">{w.todo.join(' · ')}</p></div></div>)}
        <Hazards items={ov.ridge} />
      </section>

      <section className="rise" style={{ ['--d' as string]: 3 }}>
        <div className="section-head"><h2>Emergencies</h2><span className="sub">Guided Response reports reach Earth after the signal delay</span></div>
        {ov.emergencies.length ? (
          <ul className="plain">{ov.emergencies.map(e => (
            <li key={e.id}><b>{protocol(e.protocol)}</b> <span className="muted">· day {e.day} · {e.ended_at ? `closed, ${e.outcome}` : 'in progress'}</span></li>
          ))}</ul>
        ) : <p className="muted">None so far.</p>}
      </section>

      <section className="danger-zone rise" style={{ ['--d' as string]: 4 }}>
        <div className="grow"><b>Use demo data</b><p className="small muted">Replace everything with the Odyssey 1 demo mission: four crew, the Mars itinerary, every reading and the demo story.</p></div>
        {confirm === 'demo'
          ? <div className="row"><button className="btn ghost" onClick={() => setConfirm(null)}>Cancel</button><button className="btn pri" disabled={demo.busy} onClick={() => demo.run(async () => { await onDemo(); setConfirm(null) })}>{demo.busy ? 'Loading…' : 'Replace with demo data'}</button></div>
          : <button className="btn" onClick={() => setConfirm('demo')}>Use demo data</button>}
        <ActionError error={demo.error} />
      </section>

      <section className="danger-zone rise" style={{ ['--d' as string]: 5 }}>
        <div className="grow"><b>Start from zero</b><p className="small muted">Clear the crew and the mission. Crew terminals wait for Mission Control until you register again or use the demo data.</p></div>
        {confirm === 'clear'
          ? <div className="row"><button className="btn ghost" onClick={() => setConfirm(null)}>Cancel</button><button className="btn danger" disabled={clear.busy} onClick={() => clear.run(onClear)}>{clear.busy ? 'Clearing…' : 'Clear everything'}</button></div>
          : <button className="btn" onClick={() => setConfirm('clear')}>Clear crew and mission</button>}
        <ActionError error={clear.error} />
      </section>
    </>
  )
}

/* ---------------------------------------------------------------- register: crew, then mission, then save */
// One flat form: keys are `crew.0.name` ... `crew.3.weight_kg` and `mission.callsign` ..., the same names the API
// uses in its 422 answers, so a server error lands on the field it names. Numbers and lists are typed as text.
type Values = Record<string, unknown>
const SEAT_TEXT: [string, string, number][] = [['home', 'Home city', 80], ['nationality', 'Nationality', 60], ['agency', 'Agency', 80], ['vision', 'Vision', 80],
  ['diet', 'Diet', 120], ['vaccinations', 'Vaccinations', 200], ['emergency_contact', 'Emergency contact', 200]]
const SEAT_LISTS: [string, string][] = [['languages', 'Languages'], ['allergies', 'Allergies'], ['medications', 'Medications'], ['conditions', 'Conditions']]
const SEAT_AGE = [25, 70] as const

const str = (x: unknown) => (x === null || x === undefined ? '' : String(x))
const items = (t: string) => t.split(',').map(x => x.trim()).filter(Boolean)

function seatToValues(c: SeatForm, i: number): Values {
  const o: Values = {}
  for (const [k, val] of Object.entries(c)) o[`crew.${i}.${k}`] = Array.isArray(val) ? val.join(', ') : val ?? ''
  return o
}
/** The form's values without person `j`: the people after it move up one place. */
function withoutPerson(f: Values, j: number, n: number): Values {
  const out: Values = {}
  for (const [k, val] of Object.entries(f)) {
    const m = /^crew\.(\d+)\.(.+)$/.exec(k)
    if (!m) { out[k] = val; continue }
    const i = Number(m[1])
    if (i < j) out[k] = val
    else if (i > j && i < n) out[`crew.${i - 1}.${m[2]}`] = val
  }
  return out
}
const toValues = (crew: SeatForm[], m: MissionForm): Values => ({ ...Object.assign({}, ...crew.map(seatToValues)), ...Object.fromEntries(Object.entries(m).map(([k, x]) => [`mission.${k}`, x])), 'mission.rover': m.rover === false ? 'no' : 'yes' })

/** Every rule of the registration form, by field. The server repeats them (SeatIn, MissionRegIn, _check_registration). */
function validateRegister(f: Values, n: number, presets: string[], roverPresets: string[]): Errors {
  const e: Errors = {}
  const launch = str(f['mission.launch_date'])
  const pins = new Map<string, number>()
  Array.from({ length: n }, (_, i) => i).forEach(i => {
    const g = (k: string) => str(f[`crew.${i}.${k}`])
    const put = (k: string, m: string | null) => { e[`crew.${i}.${k}`] = m }
    put('name', v.length('Name', { min: 2, max: 60 })(g('name')))
    put('role', v.length('Role', { min: 2, max: 60 })(g('role')))
    put('home', v.length('Home city', { max: 80, optional: true })(g('home')))
    put('dob', v.ageAtLaunch('Date of birth', launch, SEAT_AGE[0], SEAT_AGE[1])(g('dob')))
    put('sex', v.oneOf('Sex', SEX, true)(g('sex')))
    for (const [k, label, max] of SEAT_TEXT.slice(1)) put(k, v.length(label, { max, optional: true })(g(k)))
    for (const [k, label] of SEAT_LISTS) put(k, items(g(k)).length > 20 || items(g(k)).some(x => x.length > 60) ? `${label}: at most 20 items of 60 characters, separated by commas` : null)
    put('flights', v.number('Previous flights', { min: 0, max: 20, integer: true })(g('flights')))
    put('days_in_space', v.number('Days in space', { min: 0, max: 1000, unit: 'days', integer: true })(g('days_in_space')))
    const pin = v.pin4()(g('pin'))
    const first = pins.get(g('pin'))
    put('pin', pin ?? (first !== undefined ? `PIN is already used by person ${first + 1}; each person needs their own` : null))
    if (!pin) pins.set(g('pin'), pins.get(g('pin')) ?? i)
    put('height_cm', v.number('Height', { min: 140, max: 210, unit: 'cm' })(g('height_cm')))
    put('weight_kg', v.number('Weight', { min: 40, max: 150, unit: 'kg' })(g('weight_kg')))
    put('blood_type', v.oneOf('Blood type', BLOOD, true)(g('blood_type')))
    put('skin_type', v.oneOf('Skin type', SKIN)(g('skin_type')))
    put('handedness', v.oneOf('Dominant hand', HAND)(g('handedness')))
    put('eva', v.oneOf('EVA role', EVA.map(x => x[0]))(g('eva')))
    put('prior_dose_msv', v.number('Dose from earlier flights', { min: 0, max: 600, unit: 'mSv', optional: true })(g('prior_dose_msv')))
  })
  e['mission.callsign'] = v.length('Callsign', { min: 2, max: 24 })(str(f['mission.callsign']))
  e['mission.name'] = v.length('Mission name', { min: 2, max: 80 })(str(f['mission.name']))
  e['mission.launch_date'] = v.date('Launch date', { minYear: 2025, maxYear: 2100 })(launch)
  e['mission.preset'] = v.oneOf('Mission profile', presets)(str(f['mission.preset']))
  e['mission.rover'] = roverPresets.includes(str(f['mission.preset'])) ? v.oneOf('Rover leg', ['yes', 'no'])(str(f['mission.rover'])) : null
  return e
}

function Register({ registered, onSaved, onDemo }: { registered: boolean; onSaved: (o: ControlOverview) => void; onDemo: () => Promise<void> }) {
  const loadDemo = useAction()
  const [step, setStep] = useState(0)
  const [count, setCount] = useState(1)
  const [open, setOpen] = useState(0)
  const { data: demo } = useApi(() => api.controlDemo(), [])
  const presets = demo?.presets ?? { mars: 'Mars reference mission', iss: 'Six months on the ISS', moon: 'Lunar surface mission' }
  const roverPresets = demo?.rover_presets ?? ['mars', 'moon']
  const form = useForm<Values>({
    initial: toValues([emptySeat()], emptyMission),
    validate: f => validateRegister(f, count, Object.keys(presets), roverPresets),
    submit: async f => {
      const g = (i: number, k: string) => str(f[`crew.${i}.${k}`]).trim()
      const crew = Array.from({ length: count }, (_, i): SeatForm => ({
        seat: g(i, 'seat') || undefined, name: g(i, 'name'), role: g(i, 'role'), home: g(i, 'home'), pin: g(i, 'pin'), dob: g(i, 'dob'), sex: g(i, 'sex'), nationality: g(i, 'nationality'),
        languages: items(g(i, 'languages')), agency: g(i, 'agency'), flights: Number(g(i, 'flights')), days_in_space: Number(g(i, 'days_in_space')),
        height_cm: v.parseNumber(g(i, 'height_cm')) ?? 0, weight_kg: v.parseNumber(g(i, 'weight_kg')) ?? 0, blood_type: g(i, 'blood_type'), skin_type: g(i, 'skin_type'),
        handedness: g(i, 'handedness'), vision: g(i, 'vision'), allergies: items(g(i, 'allergies')), medications: items(g(i, 'medications')), conditions: items(g(i, 'conditions')),
        diet: g(i, 'diet'), vaccinations: g(i, 'vaccinations'), emergency_contact: g(i, 'emergency_contact'),
        eva: g(i, 'eva'), prior_dose_msv: v.parseNumber(g(i, 'prior_dose_msv')),
      }))
      const mission: MissionForm = { callsign: str(f['mission.callsign']).trim(), name: str(f['mission.name']).trim(), launch_date: str(f['mission.launch_date']), preset: str(f['mission.preset']),
        rover: roverPresets.includes(str(f['mission.preset'])) ? f['mission.rover'] !== 'no' : false }
      onSaved(await api.controlRegister(crew, mission))
    },
    // A wrong field can sit in a closed seat or on another step: open it so it can take the focus.
    reveal: key => {
      const m = /^crew\.(\d+)\./.exec(key)
      if (m) { setStep(0); setOpen(Number(m[1])) } else if (key.startsWith('mission.')) setStep(1)
    },
  })
  const addPerson = () => {
    if (count >= MAX_PEOPLE) return
    form.setValues(f => ({ ...f, ...seatToValues(emptySeat(), count) }))
    setCount(count + 1); setOpen(count)
  }
  const removePerson = (j: number) => {
    if (count <= 1) return
    form.setValues(f => withoutPerson(f, j, count))
    setCount(count - 1); setOpen(o => (o === j ? -1 : o > j ? o - 1 : o))
  }
  const seatNo = (key: string) => { const m = /^crew\.(\d+)\./.exec(key); return m ? `Person ${Number(m[1]) + 1}` : 'Mission' }
  const people = Array.from({ length: count }, (_, i) => i)
  const val = (k: string) => str(form.values[k])
  const next = (prefix: string, to: number) => { if (!form.check(k => k.startsWith(prefix)).length) setStep(to) }
  const { catalog } = useSession()
  const withRover = roverPresets.includes(val('mission.preset')) && val('mission.rover') !== 'no'
  const itinerary = demo && catalog ? demo.itineraries[val('mission.preset')]?.[withRover ? 'rover' : 'plain'] : undefined
  const allErrs = validateRegister(form.values, count, Object.keys(presets), roverPresets)
  const seatBad = (i: number) => Object.keys(allErrs).filter(k => k.startsWith(`crew.${i}.`) && allErrs[k]).length
  const seatShown = (i: number) => form.visible.filter(x => x.key.startsWith(`crew.${i}.`)).length
  return (
    <form className="register" noValidate onSubmit={form.submit}>
      <div className="row wrap rise">
        <div className="stepper">{['Crew', 'Mission', 'Review and save'].map((t, i) => (
          <button type="button" key={t} className={i === step ? 'on' : i < step ? 'done' : ''} onClick={() => setStep(i)}><span className="num">{i + 1}</span>{t}</button>
        ))}</div>
      </div>
      {registered && step === 0 && <p className="small muted rise">A crew is already registered. Saving replaces it and restarts the mission clock.</p>}
      {!registered && step === 0 && (
        <div className="set-row rise">
          <div className="grow"><b>Use demo data</b><p className="small muted">Fill everything with the Odyssey 1 demo mission: four crew, the Mars itinerary, every reading and the demo story.</p></div>
          <button type="button" className="btn" disabled={loadDemo.busy} onClick={() => loadDemo.run(onDemo)}>{loadDemo.busy ? 'Loading…' : 'Use demo data'}</button>
          <ActionError error={loadDemo.error} />
        </div>
      )}
      {step < 2 && <FormSummary form={form} describe={seatNo} />}

      {step === 0 && (
        <div className="seats rise">
          {people.map(i => (
            <div key={i} className={`seat ${open === i ? 'open' : ''}`}>
              <button type="button" className="seat-head" aria-expanded={open === i} onClick={() => setOpen(o => (o === i ? -1 : i))}>
                <span className="pdot sm neutral"><span className="ini">{val(`crew.${i}.name`) ? val(`crew.${i}.name`).split(' ').map(x => x[0]).slice(0, 2).join('') : i + 1}</span></span>
                <span className="grow"><b>{val(`crew.${i}.name`) || `Person ${i + 1}`}</b><span className="small muted">{val(`crew.${i}.role`) || 'Not filled in'}</span></span>
                {seatShown(i) ? <span className="small err">{seatShown(i)} to fix</span>
                  : <span className={`small ${seatBad(i) ? 'dim' : 'ok-text'}`}>{seatBad(i) ? 'Not complete' : 'Ready'}</span>}
              </button>
              {open === i && <SeatFields form={form} i={i} issRate={demo?.iss_dose_msv_per_day ?? 0.5} onRemove={count > 1 ? () => removePerson(i) : undefined} />}
            </div>
          ))}
          <div className="row wrap">
            <button type="button" className="btn" disabled={count >= MAX_PEOPLE} onClick={addPerson}><Icon name="plus" />Add a person</button>
            <span className="small dim">{count} of {MAX_PEOPLE} · a crew is one to six people</span>
            <span className="grow" />
            <button type="button" className="btn pri" onClick={() => next('crew.', 1)}>Next: the mission<Icon name="chev" /></button></div>
        </div>
      )}

      {step === 1 && (
        <div className="form-grid rise">
          <Field form={form} name="mission.callsign" label="Callsign" placeholder="e.g. Odyssey 1" hint="2 to 24 characters" maxLength={24} />
          <Field form={form} name="mission.name" label="Mission name" placeholder="e.g. Mars reference mission" hint="2 to 80 characters" maxLength={80} />
          <Field form={form} name="mission.launch_date" label="Launch date" type="date" hint="Between 2025 and 2100" />
          <Field form={form} name="mission.preset" label="Mission profile" as="select">{Object.entries(presets).map(([k, n]) => <option key={k} value={k}>{n}</option>)}</Field>
          {roverPresets.includes(val('mission.preset')) && (
            <Field form={form} name="mission.rover" label="Rover leg" as="select" hint="A pressurized rover traverse inside the surface stay, away from the base">
              <option value="yes">Include the rover traverse</option><option value="no">Surface stay only</option></Field>
          )}
          <p className="small muted" style={{ gridColumn: '1 / -1' }}>The profile sets the itinerary (training, launch, transfer, stay, return). Every rule on board adapts to it: goals, alerts, radiation, signal delay, Guided Response.</p>
          <div className="row" style={{ gridColumn: '1 / -1' }}><button type="button" className="btn ghost" onClick={() => setStep(0)}><Icon name="back" />Crew</button><span className="grow" /><button type="button" className="btn pri" onClick={() => next('mission.', 2)}>Next: review<Icon name="chev" /></button></div>
        </div>
      )}

      {step === 2 && (
        <div className="review rise">
          <h2>{val('mission.callsign') || 'Unnamed'} · {val('mission.name')}</h2>
          <p className="muted">{presets[val('mission.preset')]} · launch {val('mission.launch_date')}</p>
          <div className="scroll"><table className="t"><thead><tr><th>#</th><th>Name</th><th>Role</th><th>Agency</th><th>Blood</th><th>Allergies</th><th>EVA</th><th className="num">Earlier dose</th><th>PIN</th></tr></thead>
            <tbody>{people.map(i => <tr key={i}><td className="num">{i + 1}</td><td><b>{val(`crew.${i}.name`)}</b></td><td>{val(`crew.${i}.role`)}</td><td>{val(`crew.${i}.agency`)}</td><td>{val(`crew.${i}.blood_type`)}</td><td>{val(`crew.${i}.allergies`) || 'None'}</td><td>{EVA.find(x => x[0] === val(`crew.${i}.eva`))?.[1]}</td><td className="num">{val(`crew.${i}.prior_dose_msv`) ? `${val(`crew.${i}.prior_dose_msv`)} mSv` : 'Estimated'}</td><td className="num">{val(`crew.${i}.pin`) ? '••••' : '—'}</td></tr>)}</tbody></table></div>
          {itinerary && <Timeline legs={itinerary} places={catalog?.locations ?? {}} />}
          <p className="small muted">Saving sends this registration to the ship. Each astronaut opens their space with the PIN set here and can change it on board.</p>
          <FormSummary form={form} describe={seatNo} />
          <FormError form={form} />
          <div className="row"><button type="button" className="btn ghost" onClick={() => setStep(1)}><Icon name="back" />Mission</button><span className="grow" />
            <SubmitButton form={form}>Save and activate Canary</SubmitButton></div>
        </div>
      )}
    </form>
  )
}

/** Empty, the server estimates the career dose before this mission from the days already in space at the station's
 *  daily dose (domain/standards.py prior_dose). Said under the field so nobody believes it is zero. */
function priorHint(days: string, typed: string, rate: number): string {
  if (typed.trim()) return '0–600 mSv, as in the flight dosimetry record'
  const d = v.number('', { min: 0, max: 1000, integer: true })(days) ? null : Number(days)
  return d === null ? 'Estimated from days in space' : `Estimated from days in space: ${(Math.round(d * rate * 10) / 10).toLocaleString('en-US')} mSv (${d} days at ${rate} mSv/day)`
}

function SeatFields({ form, i, issRate, onRemove }: { form: ReturnType<typeof useForm<Values>>; i: number; issRate: number; onRemove?: () => void }) {
  const n = (k: string) => `crew.${i}.${k}`
  const txt = (k: string, label: string, o: { ph?: string; hint?: string; max?: number } = {}) => <Field form={form} name={n(k)} label={label} placeholder={o.ph} hint={o.hint} maxLength={o.max} />
  const num = (k: string, label: string, hint: string) => <Field form={form} name={n(k)} label={label} hint={hint} inputMode="decimal" autoComplete="off" />
  const sel = (k: string, label: string, opts: string[], required = false) => <Field form={form} name={n(k)} label={label} as="select">{!required && <option value="">—</option>}{opts.map(o => <option key={o} value={o}>{o}</option>)}</Field>
  const list = (k: string, label: string, ph = 'comma separated') => <Field form={form} name={n(k)} label={label} placeholder={ph} hint="Up to 20 items, separated by commas" />
  const [home, nationality, agency, vision, diet, vaccinations, emergency] = SEAT_TEXT
  return (
    <div className="seat-body">
      <h3>Identity</h3>
      <div className="form-grid">{txt('name', 'Full name', { hint: '2 to 60 characters', max: 60 })}{txt('role', 'Role', { ph: 'e.g. Commander', hint: '2 to 60 characters', max: 60 })}{txt('home', home[1], { max: home[2] })}
        <Field form={form} name={n('dob')} label="Date of birth" type="date" hint={`Age ${SEAT_AGE[0]}–${SEAT_AGE[1]} at launch`} />
        {sel('sex', 'Sex', SEX)}{txt('nationality', nationality[1], { max: nationality[2] })}{list('languages', 'Languages')}{txt('agency', agency[1], { max: agency[2] })}
        {num('flights', 'Previous flights', v.range(0, 20))}{num('days_in_space', 'Days in space before', v.range(0, 1000, 'days'))}
        <Field form={form} name={n('pin')} label="First PIN (4 digits)" hint="Different for each person" inputMode="numeric" maxLength={4} autoComplete="off" /></div>
      <h3>Body</h3>
      <div className="form-grid">{num('height_cm', 'Height (cm)', v.range(140, 210, 'cm'))}{num('weight_kg', 'Weight (kg)', v.range(40, 150, 'kg'))}{sel('blood_type', 'Blood type', BLOOD)}{sel('skin_type', 'Skin type (Fitzpatrick)', SKIN, true)}
        {sel('handedness', 'Dominant hand', HAND, true)}{txt('vision', vision[1], { ph: 'e.g. No correction', max: vision[2] })}</div>
      <h3>EVA and radiation</h3>
      <div className="form-grid"><Field form={form} name={n('eva')} label="EVA role" as="select" hint="Sets which NASA aerobic limit applies">{EVA.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Field>
        <Field form={form} name={n('prior_dose_msv')} label="Dose from earlier flights (mSv)" optional inputMode="decimal" autoComplete="off" hint={priorHint(str(form.values[n('days_in_space')]), str(form.values[n('prior_dose_msv')]), issRate)} /></div>
      <h3>Medical</h3>
      <div className="form-grid">{list('allergies', 'Allergies')}{list('medications', 'Medications')}{list('conditions', 'Conditions')}
        {txt('diet', diet[1], { max: diet[2] })}{txt('vaccinations', vaccinations[1], { max: vaccinations[2] })}{txt('emergency_contact', emergency[1], { ph: 'name, relation, through family support', max: emergency[2] })}</div>
      {onRemove && <div className="row"><button type="button" className="link-btn" onClick={onRemove}>Remove this person</button></div>}
    </div>
  )
}

/* ---------------------------------------------------------------- messages with the ship's medical team */
function ControlMessages({ delay }: { delay: string }) {
  const { bump } = useSession()
  const { data } = useApi(() => api.messages(), [])
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t) }, [])
  const traffic = useMemo(() => (data ?? []).filter(m => ['mission-control', 'earth'].includes(m.recipient) || m.sender === 'mission-control'), [data])
  const form = useForm({
    initial: { text: '' },
    validate: f => ({ text: v.length('Message', { max: 1000 })(f.text) }),
    submit: async f => { await api.send('mission-control', 'medical', f.text.trim()); form.reset({ text: '' }); bump() },
  })
  return (
    <div className="grid g2 rise">
      <form className="col" style={{ gap: 12 }} noValidate onSubmit={form.submit}>
        <h2>Message the ship's medical team</h2>
        <p className="small muted">It reaches the medical console after the signal delay ({delay === 'Live' ? 'live right now' : `${delay} each way`}).</p>
        <Field form={form} name="text" label="Message" as="textarea" rows={5} placeholder="e.g. Please confirm the crew is in the storm shelter." hint={`${form.values.text.length} of 1000 characters`} />
        <FormError form={form} />
        <SubmitButton form={form} busyLabel="Sending…" className="btn pri start"><Icon name="send" size={15} />Send</SubmitButton>
      </form>
      <section>
        <h2 className="traffic-h">Traffic with the ship</h2>
        <div className="col" style={{ gap: 12 }}>{traffic.map(m => {
          const eta = Math.max(0, Math.round(m.deliver_at - Date.now() / 1000))
          const out = m.sender === 'mission-control'
          return (
            <div key={m.id} className={`msg ${out ? 'out' : 'in'}`}>
              <div className="row small"><b>{out ? 'Mission Control → medical team' : `${m.sender} → ${m.recipient === 'earth' ? 'Earth' : 'Mission Control'}`}</b><span className="tag">{m.kind}</span>
                <span className="num dim right">{eta ? `${out ? 'arrives' : 'arriving'} in ${eta}s` : out ? 'delivered' : 'received'}</span></div>
              <div className="muted pre-line">{m.text.length > 400 ? `${m.text.slice(0, 400).trimEnd()}…` : m.text}</div>
            </div>)
        })}{!traffic.length && <p className="muted">No traffic yet.</p>}</div>
      </section>
    </div>
  )
}
