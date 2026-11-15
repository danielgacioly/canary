// Medical console: the only signed-in mode. Flight surgeons and the crew medical officer.
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { AlertEvent, Briefing, MedGoal, MedicalOverview } from '../api/types'
import { ActionError, Field, FormError, SubmitButton } from '../components/Field'
import PinPad from '../components/PinPad'
import { Avatar, Icon, Status, Tabs } from '../components/ui'
import { allMissing, doseOrigin, DASH, nasaLine, num } from '../lib/health'
import { useAction } from '../lib/useAction'
import { useForm } from '../lib/useForm'
import * as v from '../lib/validate'
import { useApi, useSession } from '../state/session'

const TABS = ['Triage', 'Briefings', 'Prescribe', 'Messages', 'Emergencies'] as const

export default function Medical() {
  const [signed, setSigned] = useState(api.isMedical())
  const [tab, setTab] = useState<(typeof TABS)[number]>('Triage')
  const { rev } = useSession()
  const [ov, setOv] = useState<MedicalOverview | null>(null)
  useEffect(() => {
    if (!signed) return
    api.medicalOverview().then(setOv).catch(() => { api.medicalSignOut(); setSigned(false) })
  }, [signed, rev])
  if (!signed) return <PinGate onOk={() => setSigned(true)} />
  return (
    <div className="page">
      <div className="head">
        <div><h1>Medical console</h1><p className="sub">Flight surgeons and the crew medical officer</p></div>
        <button className="btn sm right" onClick={() => { api.medicalSignOut(); setSigned(false) }}>Sign out</button>
      </div>
      <Tabs value={tab} onChange={setTab} options={TABS.map(t => [t, t] as [typeof t, string])} />
      {!ov ? <span className="lbl">Loading…</span> : ov.crew.length === 0 && tab !== 'Messages' ? (
        <p className="waiting">No crew is registered yet. Mission Control registers the crew; their health appears here once it does.</p>
      ) : (
        <>
          {tab === 'Triage' && <Triage ov={ov} />}
          {tab === 'Briefings' && <Briefings ov={ov} />}
          {tab === 'Prescribe' && <Prescribe ov={ov} />}
          {tab === 'Messages' && <Messages />}
          {tab === 'Emergencies' && <Emergencies ov={ov} />}
        </>
      )}
    </div>
  )
}

const DEMO_MEDICAL_PINS: Record<string, string> = { k: '1002', 'g-fs1': '1961' }

/** Pick the account (the crew medical officer or a ground flight surgeon), then its PIN. */
function PinGate({ onOk }: { onOk: () => void }) {
  const { catalog } = useSession()
  const { data: accounts, error } = useApi(() => api.accountsPublic(), [])
  const [who, setWho] = useState<string | null>(null)
  const options = [...(accounts?.crew.filter(c => c.cmo).map(c => ({ id: c.id, name: c.name, role: 'Crew medical officer' })) ?? []),
    ...(accounts?.ground.filter(g => g.role === 'flight_surgeon').map(g => ({ id: g.id, name: g.name, role: 'Flight surgeon' })) ?? [])]
  const person = options.find(o => o.id === who)
  return (
    <div className="page med-gate">
      {!person && (
        <div className="col" style={{ gap: 12, alignItems: 'center' }}>
          <h1>Medical console</h1>
          <p className="muted">Sign in with your own account.</p>
          {error && <p className="err">{error}</p>}
          {accounts && !options.length && <p className="muted">No medical account is registered yet. Canary Control registers them.</p>}
          {options.map(o => <button key={o.id} className="btn" onClick={() => setWho(o.id)}><b>{o.name}</b> <span className="muted">{o.role}</span></button>)}
        </div>
      )}
      {person && (
        <PinPad title={person.name} subtitle="Enter your 4-digit PIN" hint={catalog?.mode === 'demo' && DEMO_MEDICAL_PINS[person.id] ? `Demo PIN: ${DEMO_MEDICAL_PINS[person.id]}` : undefined} onCancel={() => setWho(null)}
          onSubmit={async pin => { await api.medicalSignIn(person.id, pin); onOk() }} />
      )}
    </div>
  )
}

const STD_WORD = { in: 'within', near: 'near the limit', limit: 'at the limit' } as const
const EVA_WORD = { surface: 'surface EVA', microgravity: 'microgravity EVA', none: 'no EVA' } as const
/** NASA's lines that are the same for everyone; VO2max depends on the place and the EVA role, so it is read from the data. */
const GENERIC_LIMIT: Record<string, string> = { grip: '80% of pre-flight', bone: '95% of pre-flight' }

type Person = MedicalOverview['crew'][number]

/** At most one tag: the NASA red risks that are raised, named when there is one, counted when there are several. */
function redRisks(c: Person) {
  const red = c.risks.filter(r => r.nasa_red && r.level > 0)
  if (!red.length) return null
  return { text: red.length === 1 ? red[0].name : `${red.length} NASA red risks`, title: red.map(r => r.name).join(', '), level: Math.max(...red.map(r => r.level)) }
}

/** Open alert events with who acknowledged them. The officer on board or a flight surgeon acknowledges; that stops the escalation. */
function OpenAlerts() {
  const { rev, bump } = useSession()
  const [events, setEvents] = useState<AlertEvent[] | null>(null)
  const ack = useAction('inline')
  useEffect(() => {
    const load = () => api.alertEvents(true).then(r => setEvents(r.events)).catch(() => setEvents([]))
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [rev])
  if (!events?.length) return null
  return (
    <section>
      <div className="section-head"><h2>Open alerts</h2><span className="sub">A critical alert nobody acknowledges goes to the commander, then to the flight surgeon.</span></div>
      <ul className="plain">
        {events.map(e => (
          <li key={e.id} className="row wrap" style={{ gap: 10 }}>
            <span className={`alert-line s${e.level}`}><span className="dot" /><b>{e.name}</b></span>
            <span className="grow">{e.title ?? e.key}</span>
            <span className="small muted num">level {e.level} · since day {e.opened_day}</span>
            <span className="small muted">{e.acknowledged ? `Acknowledged by ${(e.acknowledged_by_names ?? e.acknowledged_by).join(', ')}` : e.escalation_stage ? `Not acknowledged, escalated (step ${e.escalation_stage})` : 'Not acknowledged'}</span>
            {!e.acknowledged && <button className="btn sm" disabled={ack.busy} onClick={() => ack.run(async () => { await api.ackAlert(e.id); bump() })}>Acknowledge</button>}
          </li>
        ))}
      </ul>
      <ActionError error={ack.error} />
    </section>
  )
}

function Triage({ ov }: { ov: MedicalOverview }) {
  const inds = Object.keys(ov.crew[0].indicators)
  const first = (c: Person) => c.name.split(' ')[0]
  return (
    <>
      <OpenAlerts />
      <section>
        <ul className="triage">
          {ov.crew.map(c => {
            const red = redRisks(c)
            const alerts = c.alerts.filter(a => a.level > 0).slice(0, 2)
            return (
              <li key={c.id}>
                <Link to={`/crew/${c.id}`} className="triage-row" aria-label={`Open ${c.name}`}>
                  <span className="who"><b>{c.name}</b><span className="small muted">{c.role}</span></span>
                  <Status level={c.ops.level}>{c.ops.label}</Status>
                  <span className="why">
                    {c.ops.reason && <span className="small muted">{c.ops.reason}</span>}
                    {alerts.map(a => <span key={a.id} className={`alert-line s${a.level}`}><span className="dot" />{a.title}{a.since_day !== undefined && <span className="small dim num"> since day {a.since_day}</span>}</span>)}
                    {!c.ops.reason && !alerts.length && <span className="small dim">{allMissing(Object.values(c.indicators)) ? 'No data yet' : 'Nothing raised'}</span>}
                  </span>
                  {red ? <span className={`tag s${red.level}`} title={red.title}>{red.text}</span> : <span />}
                </Link>
              </li>
            )
          })}
        </ul>
      </section>
      <section>
        <div className="section-head"><h2>Every indicator, every person</h2><span className="sub">value and deviation (σ) from their own normal</span></div>
        <div className="scroll"><table className="t ind-table">
          <thead><tr><th>Indicator</th>{ov.crew.map(c => <th key={c.id} className="r">{first(c)}</th>)}<th>NASA limit</th></tr></thead>
          <tbody>
            {inds.map(k => {
              const def = ov.crew[0].indicators[k]
              const lines = [...new Set(ov.crew.map(c => nasaLine(k, c.indicators[k])?.text).filter(Boolean))]
              const limit = GENERIC_LIMIT[k] ?? (lines.length ? lines.join(' · ') : '')
              return (
                <tr key={k}>
                  <td><b>{def.name}</b> <span className="dim small">{k === 'bone' ? '% of pre-flight' : def.unit}</span></td>
                  {ov.crew.map(c => {
                    const i = c.indicators[k], s = i.standard
                    const eva = k === 'vo2' && c.standard_profile ? EVA_WORD[c.standard_profile.eva] : null
                    return (
                      <td key={c.id} className={`num r s${i.level}`}>
                        <span className={i.level ? 'c' : ''}>{i.value === null ? DASH : (k === 'bone' ? 100 + i.value : i.value).toFixed(i.dp)}</span> {i.z !== null && <span className="dim small">{i.z > 0 ? '+' : ''}{i.z.toFixed(1)}</span>}
                        {i.value === null && <div className="cell-note small dim">{i.last_measured_day !== null ? `Last measured day ${i.last_measured_day}` : 'No data yet'}</div>}
                        {i.value !== null && i.baseline === null && <div className="cell-note small dim">Learning: {i.baseline_n} of {i.baseline_need ?? 5}</div>}
                        {(eva || s) && (
                          <div className="cell-note small">
                            {eva && <div className="dim">{eva}</div>}
                            {s && <div className={`c s${s.level}`} title={s.text}>{s.item} {STD_WORD[s.status]}</div>}
                          </div>
                        )}
                      </td>
                    )
                  })}
                  <td className="small muted">{limit}</td>
                </tr>
              )
            })}
            <tr>
              <td><b>Career dose</b> <span className="dim small">mSv</span></td>
              {ov.crew.map(c => (
                <td key={c.id} className="num r">
                  {num(c.dose.career_msv)}
                  <div className="cell-note small dim">{num(c.dose.career_pct_of_limit)}%{c.dose.prior_estimate ? ' · est.' : ''}{doseOrigin(c.dose) ? ` · dose ${doseOrigin(c.dose)}` : ''}</div>
                </td>
              ))}
              <td className="small muted">{ov.crew[0].dose.career_limit_msv} mSv over a career (V1 4030)</td>
            </tr>
          </tbody>
        </table></div>
      </section>
    </>
  )
}

function Briefings({ ov }: { ov: MedicalOverview }) {
  const [who, setWho] = useState(ov.crew[0].id)
  const { data: list, setData } = useApi(() => api.briefings(who), [who])
  const { data: st } = useApi(() => api.assistantStatus(), [])
  const { bump, toast } = useSession()
  const [b, setB] = useState<Briefing | null>(null)
  const gen = useAction(), approve = useAction()
  useEffect(() => setB(list?.[0] ?? null), [list])
  return (
    <div className="med-cols">
      <section className="col">
        <div className="section-head"><h2>Weekly briefing</h2></div>
        <p className="small muted">Code computes the facts; a model, once connected, only writes the prose and cannot add numbers. The crew member approves it before it is queued for Earth.</p>
        <p className="small dim">{st ? (st.configured ? `Model: ${st.provider}` : 'No model connected: template text from the same facts.') : '…'}</p>
        <div className="row wrap">{ov.crew.map(c => <button key={c.id} className={`btn sm ${who === c.id ? 'pri' : ''}`} onClick={() => setWho(c.id)}>{c.name.split(' ')[0]}</button>)}</div>
        <button className="btn pri" disabled={gen.busy} onClick={() => gen.run(async () => { const nb = await api.briefing(who); setData([nb, ...(list ?? [])]); setB(nb) })}>{gen.busy ? 'Generating…' : 'Generate briefing'}</button>
        <ActionError error={gen.error} />
        <div className="list">{(list ?? []).map(x => <button key={x.id} className={`item s${x.status === 'draft' ? 1 : 0}`} onClick={() => setB(x)}><span className="dot" />Day {x.day} · {x.status}<span className="v">{x.bytes} B</span></button>)}</div>
      </section>
      <section className="col">
        {b ? (
          <>
            <div className="row wrap"><Status level={b.status === 'draft' ? 1 : 0}>{b.status}</Status><span className="small muted num">{b.mode === 'ai' ? 'AI prose' : 'template'} · {b.bytes} bytes</span>
              {b.status === 'draft' && <button className="btn sm pri right" disabled={approve.busy} onClick={() => approve.run(async () => { const nb = await api.approveBriefing(b.id); setB(nb); bump(); toast('Approved by the crew member and queued for Earth.') })}>{approve.busy ? 'Approving…' : 'Approve and queue'}</button>}</div>
            <ActionError error={approve.error} />
            <pre className="brief-text">{b.text}</pre>
          </>
        ) : <p className="muted">Generate a briefing to see it here.</p>}
      </section>
    </div>
  )
}

function Prescribe({ ov }: { ov: MedicalOverview }) {
  const { bump, toast } = useSession()
  const { data: goals, setData } = useApi(() => api.medGoals(), [])
  const remove = useAction()
  const form = useForm({
    initial: { who: 'all', area: 'physical', title: '', why: 'Prescribed by the medical team.', days: '7' },
    validate: f => ({
      title: v.length('Goal', { min: 3, max: 120 })(f.title),
      why: v.length('Why', { max: 200, optional: true })(f.why),
      days: v.number('Days', { min: 1, max: 60, unit: 'days', integer: true })(f.days),
    }),
    submit: async f => {
      setData(await api.addMedGoal({ who: f.who, area: f.area, title: f.title.trim(), why: f.why.trim() || 'Prescribed by the medical team.', days: Number(f.days) }))
      bump(); toast('Goal prescribed'); form.setValues({ title: '' })
    },
  })
  return (
    <div className="grid g2">
      <form className="col" noValidate onSubmit={form.submit}>
        <div className="section-head"><h2>Prescribe a goal</h2></div>
        <Field form={form} name="who" label="For" as="select"><option value="all">Whole crew</option>{ov.crew.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</Field>
        <Field form={form} name="area" label="Area" as="select"><option value="physical">Physical</option><option value="mental">Mental</option></Field>
        <Field form={form} name="title" label="Goal" placeholder="e.g. Measure pressure lying and standing, morning and night" hint="3 to 120 characters" maxLength={120} />
        <Field form={form} name="why" label="Why (the crew sees this)" hint="Up to 200 characters" maxLength={200} />
        <Field form={form} name="days" label="Days" hint={v.range(1, 60, 'days')} inputMode="numeric" />
        <FormError form={form} />
        <SubmitButton form={form}>Prescribe</SubmitButton>
      </form>
      <section><div className="section-head"><h2>Active prescriptions</h2></div>
        <div className="col">{(goals ?? []).map((g: MedGoal) => (
          <div key={g.id} className="goal"><div className="grow"><b>{g.title}</b><div className="small dim">{g.who === 'all' ? 'Whole crew' : ov.crew.find(c => c.id === g.who)?.name} · day {g.from_day} to {g.to_day} · {g.area}</div></div>
            <button className="btn sm" disabled={remove.busy} onClick={() => remove.run(async () => {
              const reason = window.prompt('Why is this goal being removed? It stays in the record, marked as voided.')?.trim()
              if (!reason) return
              setData(await api.delMedGoal(g.id, reason)); bump()
            })}>Remove</button></div>))}
          <ActionError error={remove.error} />
          {!goals?.length && <p className="muted">None. Guided Response adds follow-up care here automatically.</p>}</div>
      </section>
    </div>
  )
}

function Messages() {
  const { me, catalog, bump } = useSession()
  const { data } = useApi(() => api.messages(), [])
  const { data: accounts } = useApi(() => api.accountsPublic(), [])
  const nameOf = (id: string) => accounts?.crew.find(c => c.id === id)?.name ?? accounts?.ground.find(g => g.id === id)?.name ?? id
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t) }, [])
  const form = useForm({
    initial: { to: 'crew', text: '' },
    validate: f => ({ text: v.length('Message', { max: 1000 })(f.text) }),
    submit: async f => { await api.send('medical', f.to, f.text.trim()); form.reset({ to: f.to, text: '' }); bump() },
  })
  return (
    <div className="grid g2">
      <form className="col" noValidate onSubmit={form.submit}>
        <div className="section-head"><h2>Messages</h2></div><p className="small muted">It arrives after the real delay for where the crew is (20× faster in the demo).</p>
        <Field form={form} name="to" label="To" as="select">
          <option value="mission-control">Mission Control (Earth)</option><option value="crew">Whole crew</option>{catalog?.crew.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</Field>
        <Field form={form} name="text" label="Message" as="textarea" rows={4} hint={`${String(form.values.text).length} of 1000 characters`} />
        <FormError form={form} />
        <SubmitButton form={form} busyLabel="Sending…" className="btn pri start"><Icon name="send" size={15} />Send</SubmitButton>
        <span className="small dim">Sent as the account signed in to this console{me ? ` · terminal of ${catalog?.crew.find(c => c.id === me)?.name}` : ''}</span>
      </form>
      <section><div className="section-head"><h2>Link log</h2></div>
        <ul className="plain link-log">{(data ?? []).map(m => {
          const eta = Math.max(0, Math.round(m.deliver_at - Date.now() / 1000))
          return (
            <li key={m.id} className="small">
              <span className={`dot s${eta ? 1 : 0}`} />
              <div className="grow"><b>{nameOf(m.sender)} → {nameOf(m.recipient)}</b> <span className="dim">{m.kind}</span><div className="muted msg-text">{m.text.slice(0, 220)}</div></div>
              <span className="num dim">{eta ? `in ${eta}s` : 'delivered'}</span>
            </li>)
        })}</ul>
        {!data?.length && <p className="muted">No traffic yet.</p>}
      </section>
    </div>
  )
}

function Emergencies({ ov }: { ov: MedicalOverview }) {
  return (
    <section>
      <div className="section-head"><h2>Guided Response log</h2></div>
      {!ov.emergencies.length && <p className="muted">No emergencies yet. Hold the red button to run one.</p>}
      <ul className="plain emergencies">{ov.emergencies.map(e => (
        <li key={e.id}>
          <div className="row wrap"><b>{e.protocol ?? 'triage'}</b><span className="small muted">day {e.day} · {e.location}</span>
            {e.patient && <span className="row small muted">patient <Avatar initials={e.patient.toUpperCase()} /></span>}
            <span className="right small">{e.outcome ?? 'open'}</span></div>
          <div className="col small emg-log">{e.log.map(([t, x], i) => <span key={i}><span className="num dim">{String(Math.floor(t / 60)).padStart(2, '0')}:{String(t % 60).padStart(2, '0')}</span> {x}</span>)}</div>
        </li>))}</ul>
    </section>
  )
}
