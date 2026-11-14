// Canary Control: the Mission Control side of the system, in its own mode.
// It registers the crew and the mission (no accounts on board), follows each person the way
// Earth may (operational status as the ship's medical team reports it, participation, hazards),
// and exchanges delayed messages with the ship's medical console.
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { ControlOverview, MissionForm, SeatForm } from '../api/types'
import { Dot } from '../components/People'
import Hazards from '../components/Hazards'
import PinPad from '../components/PinPad'
import Stars from '../components/Stars'
import { CanaryMark, Icon, Loading, Tabs } from '../components/ui'
import { useApi, useSession } from '../state/session'

type Tab = 'dashboard' | 'register' | 'messages'
const SEATS = ['h', 'k', 'a', 't']
const BLOOD = ['O−', 'O+', 'A−', 'A+', 'B−', 'B+', 'AB−', 'AB+']
const SKIN = ['I', 'II', 'III', 'IV', 'V', 'VI']

const emptySeat = (seat: string): SeatForm => ({
  seat, name: '', role: '', home: '', pin: '', dob: '1990-01-01', sex: '', nationality: '', languages: [], agency: '', flights: 0,
  days_in_space: 0, height_cm: 170, weight_kg: 70, blood_type: '', skin_type: 'III', handedness: 'Right', vision: '', allergies: [],
  medications: [], conditions: [], diet: '', vaccinations: '', emergency_contact: '',
})
const emptyMission: MissionForm = { callsign: '', name: '', launch_date: '2035-06-01', preset: 'mars' }

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
        <p className="muted reveal" style={{ maxWidth: '46ch', textAlign: 'center' }}>Mission Control's side of Canary: register the crew and the mission, follow each person the way Earth may, and talk to the ship's medical team.</p>
        <PinPad title="Mission Control" subtitle="Enter the 4-digit Mission Control PIN" hint="Demo PIN: 4242" onSubmit={async pin => { await api.controlSignIn(pin); onOk() }} />
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
  return (
    <div className="control">
      <header className="control-top">
        <span className="brand"><CanaryMark size={22} />CANARY CONTROL</span>
        <span className="small muted">{ov.registered ? `${ov.overview.callsign} · ${ov.mission.day_label} · ${ov.mission.place.name}` : 'No mission registered'}</span>
        <div className="right row" style={{ gap: 8 }}>
          <button className="btn sm" onClick={() => nav('/crew')}><Icon name="back" />Back to the crew view</button>
          <button className="btn sm ghost" onClick={onSignOut}>Sign out</button>
        </div>
      </header>
      <div className="control-page">
        <Tabs value={tab} onChange={setTab} options={[['dashboard', 'Dashboard'], ['register', 'Register crew and mission'], ['messages', 'Messages']]} />
        {tab === 'dashboard' && <Dashboard ov={ov} onClear={async () => { refresh(await api.controlClear()); setTab('register') }} onRegister={() => setTab('register')} />}
        {tab === 'register' && <Register registered={ov.registered} onSaved={o => { refresh(o); setTab('dashboard') }} />}
        {tab === 'messages' && <ControlMessages delay={ov.mission.place.reply} />}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- dashboard */
function Dashboard({ ov, onClear, onRegister }: { ov: ControlOverview; onClear: () => void; onRegister: () => void }) {
  const [confirm, setConfirm] = useState(false)
  if (!ov.registered) {
    return (
      <div className="empty-ctl rise">
        <h2>Nothing registered</h2>
        <p className="muted">The crew terminals are waiting. Register the four astronauts and the mission to bring Canary to life.</p>
        <button className="btn pri" onClick={onRegister}>Register crew and mission</button>
      </div>
    )
  }
  const ms = ov.mission
  return (
    <>
      <div className="stats rise">
        <div className="stat"><div className="k">Mission</div><b style={{ fontSize: 18 }}>{ov.overview.callsign}</b><div className="s">{ov.overview.name}</div></div>
        <div className="stat"><div className="k">Mission time</div><b style={{ fontSize: 18 }}>{ms.day_label}</b><div className="s">{ms.leg.label || ms.place.name}</div></div>
        <div className="stat"><div className="k">Signal delay</div><b style={{ fontSize: 18 }}>{ms.place.reply}</b><div className="s">each way</div></div>
        <div className="stat"><div className="k">Mission dose</div><b style={{ fontSize: 18 }}>{ov.dose.mission_msv} mSv</b><div className="s">{ov.dose.pct_of_limit}% of the career limit</div></div>
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
            <li key={e.id}><b>{e.protocol ?? 'Triage'}</b> <span className="muted">· day {e.day} · {e.ended_at ? `closed, ${e.outcome}` : 'in progress'}</span></li>
          ))}</ul>
        ) : <p className="muted">None so far.</p>}
      </section>

      <section className="danger-zone rise" style={{ ['--d' as string]: 4 }}>
        <div className="grow"><b>Start from zero</b><p className="small muted">Clear the crew and the mission. Every crew terminal shows "Waiting for Mission Control" until you register again. A demo reset brings the demo back.</p></div>
        {confirm
          ? <div className="row"><button className="btn ghost" onClick={() => setConfirm(false)}>Cancel</button><button className="btn danger" onClick={onClear}>Clear everything</button></div>
          : <button className="btn" onClick={() => setConfirm(true)}>Clear crew and mission</button>}
      </section>
    </>
  )
}

/* ---------------------------------------------------------------- register: crew, then mission, then save */
function Register({ registered, onSaved }: { registered: boolean; onSaved: (o: ControlOverview) => void }) {
  const [step, setStep] = useState(0)
  const [crew, setCrew] = useState<SeatForm[]>(SEATS.map(emptySeat))
  const [m, setM] = useState<MissionForm>(emptyMission)
  const [open, setOpen] = useState('h')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const { data: demo } = useApi(() => api.controlDemo(), [])
  const presets = demo?.presets ?? { mars: 'Mars reference mission', iss: 'Six months on the ISS', moon: 'Lunar surface mission' }
  const fill = () => { if (demo) { setCrew(demo.crew.map(c => ({ ...c }))); setM({ ...demo.mission }); setErr('') } }
  const set = (i: number, patch: Partial<SeatForm>) => setCrew(cs => cs.map((c, j) => (j === i ? { ...c, ...patch } : c)))
  const crewOk = crew.every(c => c.name.trim().length >= 2 && c.role.trim().length >= 2 && /^\d{4}$/.test(c.pin))
  const missionOk = m.callsign.trim().length >= 2 && m.name.trim().length >= 2 && /^\d{4}-\d{2}-\d{2}$/.test(m.launch_date)
  const save = async () => {
    setBusy(true); setErr('')
    try { onSaved(await api.controlRegister(crew, m)) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <div className="register">
      <div className="row wrap rise">
        <div className="stepper">{['Crew', 'Mission', 'Review and save'].map((t, i) => (
          <button key={t} className={i === step ? 'on' : i < step ? 'done' : ''} onClick={() => setStep(i)}><span className="num">{i + 1}</span>{t}</button>
        ))}</div>
        <button className="btn right" onClick={fill} disabled={!demo}><Icon name="plus" />Fill with the demo crew and mission</button>
      </div>
      {registered && step === 0 && <p className="small muted rise">A crew is already registered. Saving replaces it and restarts the mission clock.</p>}

      {step === 0 && (
        <div className="seats rise">
          {crew.map((c, i) => (
            <div key={c.seat} className={`seat ${open === c.seat ? 'open' : ''}`}>
              <button className="seat-head" onClick={() => setOpen(o => (o === c.seat ? '' : c.seat))}>
                <span className="pdot sm neutral"><span className="ini">{c.name ? c.name.split(' ').map(x => x[0]).slice(0, 2).join('') : i + 1}</span></span>
                <span className="grow"><b>{c.name || `Seat ${i + 1}`}</b><span className="small muted">{c.role || 'Not filled in'}</span></span>
                <span className={`small ${c.name && c.role && /^\d{4}$/.test(c.pin) ? 'ok-text' : 'dim'}`}>{c.name && c.role && /^\d{4}$/.test(c.pin) ? 'Ready' : 'Needs name, role and PIN'}</span>
              </button>
              {open === c.seat && <SeatFields c={c} set={patch => set(i, patch)} />}
            </div>
          ))}
          <div className="row"><span className="grow" /><button className="btn pri" disabled={!crewOk} onClick={() => setStep(1)}>Next: the mission<Icon name="chev" /></button></div>
        </div>
      )}

      {step === 1 && (
        <div className="form-grid rise">
          <label className="field"><span className="lbl">Callsign</span><input value={m.callsign} onChange={e => setM({ ...m, callsign: e.target.value })} placeholder="e.g. Odyssey 1" /></label>
          <label className="field"><span className="lbl">Mission name</span><input value={m.name} onChange={e => setM({ ...m, name: e.target.value })} placeholder="e.g. Mars reference mission" /></label>
          <label className="field"><span className="lbl">Launch date</span><input type="date" value={m.launch_date} onChange={e => setM({ ...m, launch_date: e.target.value })} /></label>
          <label className="field"><span className="lbl">Mission profile</span>
            <select value={m.preset} onChange={e => setM({ ...m, preset: e.target.value })}>{Object.entries(presets).map(([k, n]) => <option key={k} value={k}>{n}</option>)}</select></label>
          <p className="small muted" style={{ gridColumn: '1 / -1' }}>The profile sets the itinerary (training, launch, transfer, stay, return). Every rule on board adapts to it: goals, alerts, radiation, signal delay, Guided Response.</p>
          <div className="row" style={{ gridColumn: '1 / -1' }}><button className="btn ghost" onClick={() => setStep(0)}><Icon name="back" />Crew</button><span className="grow" /><button className="btn pri" disabled={!missionOk} onClick={() => setStep(2)}>Next: review<Icon name="chev" /></button></div>
        </div>
      )}

      {step === 2 && (
        <div className="review rise">
          <h2>{m.callsign || 'Unnamed'} · {m.name}</h2>
          <p className="muted">{presets[m.preset]} · launch {m.launch_date}</p>
          <table className="t"><thead><tr><th>Seat</th><th>Name</th><th>Role</th><th>Agency</th><th>Blood</th><th>Allergies</th><th>PIN</th></tr></thead>
            <tbody>{crew.map((c, i) => <tr key={c.seat}><td className="num">{i + 1}</td><td><b>{c.name}</b></td><td>{c.role}</td><td>{c.agency}</td><td>{c.blood_type}</td><td>{c.allergies.join(', ') || 'None'}</td><td className="num">{c.pin ? '••••' : '—'}</td></tr>)}</tbody></table>
          <p className="small muted">Saving sends this registration to the ship. Each astronaut opens their space with the PIN set here and can change it on board.</p>
          {err && <p className="small" style={{ color: 'var(--act)' }}>{err}</p>}
          <div className="row"><button className="btn ghost" onClick={() => setStep(1)}><Icon name="back" />Mission</button><span className="grow" />
            <button className="btn pri" disabled={!crewOk || !missionOk || busy} onClick={save}>{busy ? 'Saving…' : 'Save and activate Canary'}</button></div>
        </div>
      )}
    </div>
  )
}

function SeatFields({ c, set }: { c: SeatForm; set: (p: Partial<SeatForm>) => void }) {
  const txt = (k: keyof SeatForm, label: string, ph = '') => <label className="field"><span className="lbl">{label}</span><input value={String(c[k] ?? '')} placeholder={ph} onChange={e => set({ [k]: e.target.value } as Partial<SeatForm>)} /></label>
  const num = (k: keyof SeatForm, label: string) => <label className="field"><span className="lbl">{label}</span><input type="number" value={Number(c[k])} onChange={e => set({ [k]: Number(e.target.value) } as Partial<SeatForm>)} /></label>
  const list = (k: keyof SeatForm, label: string, ph = '') => <label className="field"><span className="lbl">{label}</span><input value={(c[k] as string[]).join(', ')} placeholder={ph} onChange={e => set({ [k]: e.target.value.split(',').map(x => x.trim()).filter(Boolean) } as Partial<SeatForm>)} /></label>
  const sel = (k: keyof SeatForm, label: string, opts: string[]) => <label className="field"><span className="lbl">{label}</span><select value={String(c[k])} onChange={e => set({ [k]: e.target.value } as Partial<SeatForm>)}><option value="">—</option>{opts.map(o => <option key={o} value={o}>{o}</option>)}</select></label>
  return (
    <div className="seat-body">
      <h3>Identity</h3>
      <div className="form-grid">{txt('name', 'Full name')}{txt('role', 'Role', 'e.g. Commander')}{txt('home', 'Home city')}
        <label className="field"><span className="lbl">Date of birth</span><input type="date" value={c.dob} onChange={e => set({ dob: e.target.value })} /></label>
        {sel('sex', 'Sex', ['Female', 'Male', 'Other'])}{txt('nationality', 'Nationality')}{list('languages', 'Languages', 'comma separated')}{txt('agency', 'Agency')}
        {num('flights', 'Previous flights')}{num('days_in_space', 'Days in space before')}
        <label className="field"><span className="lbl">First PIN (4 digits)</span><input inputMode="numeric" maxLength={4} value={c.pin} onChange={e => set({ pin: e.target.value.replace(/\D/g, '').slice(0, 4) })} /></label></div>
      <h3>Body</h3>
      <div className="form-grid">{num('height_cm', 'Height (cm)')}{num('weight_kg', 'Weight (kg)')}{sel('blood_type', 'Blood type', BLOOD)}{sel('skin_type', 'Skin type (Fitzpatrick)', SKIN)}
        {sel('handedness', 'Dominant hand', ['Right', 'Left'])}{txt('vision', 'Vision', 'e.g. No correction')}</div>
      <h3>Medical</h3>
      <div className="form-grid">{list('allergies', 'Allergies', 'comma separated')}{list('medications', 'Medications', 'comma separated')}{list('conditions', 'Conditions', 'comma separated')}
        {txt('diet', 'Diet')}{txt('vaccinations', 'Vaccinations')}{txt('emergency_contact', 'Emergency contact', 'name, relation, through family support')}</div>
    </div>
  )
}

/* ---------------------------------------------------------------- messages with the ship's medical team */
function ControlMessages({ delay }: { delay: string }) {
  const { bump } = useSession()
  const { data } = useApi(() => api.messages(), [])
  const [text, setText] = useState('')
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t) }, [])
  const traffic = useMemo(() => (data ?? []).filter(m => ['mission-control', 'earth'].includes(m.recipient) || m.sender === 'mission-control'), [data])
  return (
    <div className="grid g2 rise">
      <form className="col" style={{ gap: 12 }} onSubmit={async e => { e.preventDefault(); await api.send('mission-control', 'medical', text); setText(''); bump() }}>
        <h2>Message the ship's medical team</h2>
        <p className="small muted">It reaches the medical console after the signal delay ({delay === 'Live' ? 'live right now' : `${delay} each way`}, 20× faster in the demo).</p>
        <textarea required rows={5} value={text} onChange={e => setText(e.target.value)} className="in" placeholder="e.g. Please confirm the crew is in the storm shelter." />
        <button className="btn pri" style={{ alignSelf: 'flex-start' }} disabled={!text.trim()}><Icon name="send" size={15} />Send</button>
      </form>
      <section>
        <h2 style={{ marginBottom: 12 }}>Traffic with the ship</h2>
        <div className="col" style={{ gap: 12 }}>{traffic.map(m => {
          const eta = Math.max(0, Math.round(m.deliver_at - Date.now() / 1000))
          const out = m.sender === 'mission-control'
          return (
            <div key={m.id} className={`msg ${out ? 'out' : 'in'}`}>
              <div className="row small"><b>{out ? 'Mission Control → medical team' : `${m.sender} → ${m.recipient === 'earth' ? 'Earth' : 'Mission Control'}`}</b><span className="tag">{m.kind}</span>
                <span className="num dim right">{eta ? `${out ? 'arrives' : 'arriving'} in ${eta}s` : out ? 'delivered' : 'received'}</span></div>
              <div className="muted" style={{ whiteSpace: 'pre-line' }}>{m.text.slice(0, 400)}</div>
            </div>)
        })}{!traffic.length && <p className="muted">No traffic yet.</p>}</div>
      </section>
    </div>
  )
}
