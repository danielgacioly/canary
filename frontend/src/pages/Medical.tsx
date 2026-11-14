// Medical console: the only signed-in mode. Flight surgeons and the crew medical officer.
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Briefing, MedGoal, MedicalOverview } from '../api/types'
import { ActionError, Field, FieldGroup, FormError, SubmitButton } from '../components/Field'
import PinPad from '../components/PinPad'
import { Avatar, Icon, Status, Tabs } from '../components/ui'
import { useAction } from '../lib/useAction'
import { useForm } from '../lib/useForm'
import * as v from '../lib/validate'
import { useApi, useSession } from '../state/session'

const TABS = ['Triage', 'Briefings', 'Prescribe', 'Alert rules', 'Messages', 'Emergencies'] as const

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
      {!ov ? <span className="lbl">Loading…</span> : (
        <>
          {tab === 'Triage' && <Triage ov={ov} />}
          {tab === 'Briefings' && <Briefings ov={ov} />}
          {tab === 'Prescribe' && <Prescribe ov={ov} />}
          {tab === 'Alert rules' && <Rules ov={ov} />}
          {tab === 'Messages' && <Messages />}
          {tab === 'Emergencies' && <Emergencies ov={ov} />}
        </>
      )}
    </div>
  )
}

function PinGate({ onOk }: { onOk: () => void }) {
  return (
    <div className="page" style={{ alignItems: 'center', paddingTop: 48 }}>
      <section className="card rise" style={{ width: 'min(420px,100%)', padding: '28px 20px 22px' }}>
        <PinPad title="Medical console" subtitle="The crew has no accounts. Only the medical team signs in with a 4-digit PIN." hint="Demo PIN: 1961"
          onSubmit={async pin => { await api.medicalSignIn(pin); onOk() }} />
      </section>
    </div>
  )
}

function Triage({ ov }: { ov: MedicalOverview }) {
  const inds = Object.keys(ov.crew[0].indicators)
  return (
    <>
      <div className="grid g4">{ov.crew.map(c => (
        <div key={c.id} className="card col" style={{ gap: 8 }}>
          <div className="row"><b>{c.name}</b></div>
          <span className="small muted">{c.role}</span>
          <div className="ops-line"><span className="lbl">Operational status</span>
            <span className={`status s${c.ops.level}`}><span className="dot" />{c.ops.label}</span></div>
          {c.ops.reason && <span className="small muted">{c.ops.reason}</span>}
          <div className="row small"><span style={{ color: 'var(--physical)' }}>Physical {c.areas.physical.score}</span><span style={{ color: 'var(--mental)' }}>Mental {c.areas.mental.score}</span></div>
          {c.alerts.slice(0, 3).map(a => <span key={a.id} className={`small s${a.level} c`}>● {a.title}</span>)}
        </div>))}</div>
      {ov.notices.length > 0 && <section className="card">
        <div className="head"><h2>Critical alerts sent</h2><span className="small muted">once per episode · to the medical officer, or the substitute</span></div>
        {ov.notices.map(n => <div key={`${n.crew_id}${n.alert_id}${n.since_day}`} className="small">
          <b>{n.name}</b> · {n.title} <span className="muted">since day {n.since_day} · sent day {n.day} to {n.to_name}</span></div>)}
      </section>}
      <section className="card">
        <div className="head"><h2>Every indicator, every person</h2><span className="small muted">value · deviation from own baseline (σ)</span></div>
        <div className="scroll"><table className="t">
          <thead><tr><th>Indicator</th>{ov.crew.map(c => <th key={c.id}>{c.name.split(' ')[0]}</th>)}</tr></thead>
          <tbody>{inds.map(k => (
            <tr key={k}><td><b>{ov.crew[0].indicators[k].name}</b> <span className="dim small">{ov.crew[0].indicators[k].unit}</span></td>
              {ov.crew.map(c => { const i = c.indicators[k]; return <td key={c.id} className={`num s${i.level}`}><span className={i.level ? 'c' : ''}>{i.value.toFixed(i.dp)}</span> <span className="dim small">{i.z > 0 ? '+' : ''}{i.z.toFixed(1)}</span></td> })}</tr>))}</tbody>
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
    <div className="grid" style={{ gridTemplateColumns: 'minmax(0,1fr) minmax(0,1.4fr)' }}>
      <section className="card col">
        <h2>Weekly briefing</h2>
        <p className="small muted">Code computes the facts; a model, once connected, only writes the prose and cannot add numbers. The crew member approves it before it is queued for Earth.</p>
        <div className="slot small">{st ? (st.configured ? `Model: ${st.provider}` : 'No model connected: template text from the same facts.') : '…'}</div>
        <div className="row wrap">{ov.crew.map(c => <button key={c.id} className={`btn sm ${who === c.id ? 'pri' : ''}`} onClick={() => setWho(c.id)}>{c.name.split(' ')[0]}</button>)}</div>
        <button className="btn pri" disabled={gen.busy} onClick={() => gen.run(async () => { const nb = await api.briefing(who); setData([nb, ...(list ?? [])]); setB(nb) })}>{gen.busy ? 'Generating…' : 'Generate briefing'}</button>
        <ActionError error={gen.error} />
        <div className="list">{(list ?? []).map(x => <button key={x.id} className={`item s${x.status === 'draft' ? 1 : 0}`} onClick={() => setB(x)}><span className="dot" />Day {x.day} · {x.status}<span className="v">{x.bytes} B</span></button>)}</div>
      </section>
      <section className="card">
        {b ? (
          <>
            <div className="head"><span className="tag">{b.mode === 'ai' ? 'AI prose' : 'template'}</span><span className="tag">{b.bytes} bytes</span><Status level={b.status === 'draft' ? 1 : 0}>{b.status}</Status>
              {b.status === 'draft' && <button className="btn sm pri right" disabled={approve.busy} onClick={() => approve.run(async () => { const nb = await api.approveBriefing(b.id); setB(nb); bump(); toast('Approved by the crew member and queued for Earth.') })}>{approve.busy ? 'Approving…' : 'Approve and queue'}</button>}</div>
            <ActionError error={approve.error} />
            <pre style={{ whiteSpace: 'pre-wrap', font: '500 13px/1.7 var(--f-mono)', margin: 0, color: 'var(--ink)' }}>{b.text}</pre>
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
      <form className="card col" noValidate onSubmit={form.submit}>
        <h2>Prescribe a goal</h2>
        <Field form={form} name="who" label="For" as="select"><option value="all">Whole crew</option>{ov.crew.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</Field>
        <Field form={form} name="area" label="Area" as="select"><option value="physical">Physical</option><option value="mental">Mental</option></Field>
        <Field form={form} name="title" label="Goal" placeholder="e.g. Measure pressure lying and standing, morning and night" hint="3 to 120 characters" maxLength={120} />
        <Field form={form} name="why" label="Why (the crew sees this)" hint="Up to 200 characters" maxLength={200} />
        <Field form={form} name="days" label="Days" hint={v.range(1, 60, 'days')} inputMode="numeric" />
        <FormError form={form} />
        <SubmitButton form={form}>Prescribe</SubmitButton>
      </form>
      <section className="card"><div className="head"><h2>Active prescriptions</h2></div>
        <div className="col" style={{ gap: 8 }}>{(goals ?? []).map((g: MedGoal) => (
          <div key={g.id} className="goal"><div className="grow"><b>{g.title}</b><div className="small dim">{g.who === 'all' ? 'Whole crew' : ov.crew.find(c => c.id === g.who)?.name} · day {g.from_day} to {g.to_day} · {g.area}</div></div>
            <button className="btn sm" disabled={remove.busy} onClick={() => remove.run(async () => { setData(await api.delMedGoal(g.id)); bump() })}>Remove</button></div>))}
          <ActionError error={remove.error} />
          {!goals?.length && <p className="muted">None. Guided Response adds follow-up care here automatically.</p>}</div>
      </section>
    </div>
  )
}

function Rules({ ov }: { ov: MedicalOverview }) {
  const { bump, toast } = useSession()
  const form = useForm({
    initial: { watch: ov.thresholds.watch, act: ov.thresholds.act },
    validate: f => ({ act: f.act > f.watch ? null : `Act (${f.act.toFixed(1)} σ) must be above watch (${f.watch.toFixed(1)} σ). Raise act or lower watch.` }),
    submit: async f => { await api.setThresholds(f.watch, f.act); bump(); toast('Alert rules updated for the whole crew') },
  })
  const sliders = [['watch', 'Watch from', 0.5, 4, 'var(--watch)'], ['act', 'Act from', 1, 5, 'var(--act)']] as const
  return (
    <form className="card col" style={{ maxWidth: 720 }} noValidate onSubmit={form.submit}>
      <h2>When Canary speaks up</h2>
      <p className="muted">Each indicator is compared with that person's own pre-flight normal. The distance is measured in their personal spread (σ). Lower thresholds mean earlier, more frequent alerts.</p>
      {sliders.map(([k, l, min, max, c]) => (
        <FieldGroup key={k} form={form} name={k} label={<span className="row"><span>{l}</span><b className="num right" style={{ color: c }}>{form.values[k].toFixed(1)} σ</b></span>} hint={`${min}–${max} σ`}>
          <input type="range" min={min} max={max} step={0.1} value={form.values[k]} aria-label={l} onChange={e => { form.set(k, +e.target.value); form.touch('act') }} />
        </FieldGroup>
      ))}
      <FormError form={form} />
      <SubmitButton form={form} className="btn pri start">Apply to crew</SubmitButton>
      <div className="hr" />
      <span className="lbl">Cross-signal rules (always on)</span>
      <ul className="steps">
        <li>Sleep + mood + reaction time together → behavioural alert, reaction test, 3-night plan</li>
        <li>High pulse + low water in the first 72 h → space sickness, hydration goals</li>
        <li>Low pressure + high pulse in partial gravity → re-adaptation, slow standing</li>
        <li>Wavy Amsler grid → eye alert (SANS screen)</li>
        <li>Solar particle event → everyone to shelter, radiation protocol</li>
      </ul>
    </form>
  )
}

function Messages() {
  const { me, catalog, bump } = useSession()
  const { data } = useApi(() => api.messages(), [])
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t) }, [])
  const form = useForm({
    initial: { to: 'crew', text: '' },
    validate: f => ({ text: v.length('Message', { max: 1000 })(f.text) }),
    submit: async f => { await api.send(f.to === 'mission-control' ? 'ship medical team' : 'flight surgeon', f.to, f.text.trim()); form.reset({ to: f.to, text: '' }); bump() },
  })
  return (
    <div className="grid g2">
      <form className="card col" noValidate onSubmit={form.submit}>
        <h2>Messages</h2><p className="small muted">It arrives after the real delay for where the crew is (20× faster in the demo).</p>
        <Field form={form} name="to" label="To" as="select">
          <option value="mission-control">Mission Control (Earth)</option><option value="crew">Whole crew</option>{catalog?.crew.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</Field>
        <Field form={form} name="text" label="Message" as="textarea" rows={4} hint={`${String(form.values.text).length} of 1000 characters`} />
        <FormError form={form} />
        <SubmitButton form={form} busyLabel="Sending…" className="btn pri start"><Icon name="send" size={15} />Send</SubmitButton>
        <span className="small dim">Signed as flight surgeon{me ? ` · terminal of ${catalog?.crew.find(c => c.id === me)?.name}` : ''}</span>
      </form>
      <section className="card"><div className="head"><h2>Link log</h2></div>
        <div className="col" style={{ gap: 10 }}>{(data ?? []).map(m => {
          const eta = Math.max(0, Math.round(m.deliver_at - Date.now() / 1000))
          return (
            <div key={m.id} className="row small" style={{ alignItems: 'flex-start' }}>
              <span className={`dot s${eta ? 1 : 0}`} style={{ marginTop: 6 }} />
              <div className="grow"><b>{m.sender} → {m.recipient}</b> <span className="tag">{m.kind}</span><div className="muted" style={{ whiteSpace: 'pre-line' }}>{m.text.slice(0, 220)}</div></div>
              <span className="num dim">{eta ? `in ${eta}s` : 'delivered'}</span>
            </div>)
        })}{!data?.length && <p className="muted">No traffic yet.</p>}</div>
      </section>
    </div>
  )
}

function Emergencies({ ov }: { ov: MedicalOverview }) {
  return (
    <section className="card"><div className="head"><h2>Guided Response log</h2></div>
      {!ov.emergencies.length && <p className="muted">No emergencies yet. Hold the red button to run one.</p>}
      <div className="col" style={{ gap: 12 }}>{ov.emergencies.map(e => (
        <div key={e.id} className="card pad-sm">
          <div className="row"><b>{e.protocol ?? 'triage'}</b><span className="small muted">day {e.day} · {e.location}</span>
            {e.patient && <span className="row small" style={{ gap: 6 }}><Avatar initials={e.patient.toUpperCase()} />patient</span>}
            <span className="right small">{e.outcome ?? 'open'}</span></div>
          <div className="col small" style={{ gap: 2, marginTop: 8 }}>{e.log.map(([t, x], i) => <span key={i}><span className="num dim">{String(Math.floor(t / 60)).padStart(2, '0')}:{String(t % 60).padStart(2, '0')}</span> {x}</span>)}</div>
        </div>))}</div>
    </section>
  )
}
