// Canary Control, Data: how data gets in and what Mission Control may know about it.
// Flat rows, no cards. Mission Control sees counts, dates and the clock here, never a reading's value and nothing about anyone's health.
import { useRef, useState } from 'react'
import { ApiError, api, type FieldIssue } from '../api/client'
import type { DataStatus, ImportResult, SpaceEvent } from '../api/types'
import { ActionError, Field, FieldGroup, FormError, SubmitButton } from '../components/Field'
import { Loading } from '../components/ui'
import { clockDate, clockLine } from '../lib/clock'
import { useAction } from '../lib/useAction'
import { useForm } from '../lib/useForm'
import * as v from '../lib/validate'
import { useApi, useSession } from '../state/session'

const BUNDLED: [string, string][] = [['odyssey1-mars', 'Odyssey 1, Mars'], ['odyssey1-moon', 'Odyssey 1, Moon'], ['odyssey1-iss', 'Odyssey 1, ISS']]
const MAX_UPLOAD_MB = 120
const SHOWN_ERRORS = 20

/** The sentence under the load control: what was stored. */
const loaded = (r: ImportResult) => `Loaded ${r.accepted.observations} observations, ${r.accepted.goal_log} goal entries, ${r.accepted.space_events} events`

export default function ControlData() {
  const { data: status, setData } = useApi<DataStatus>(() => api.controlDataStatus(), [])
  if (!status) return <Loading what="data" />
  const refresh = () => api.controlDataStatus().then(setData).catch(() => undefined)
  return (
    <>
      <Package status={status} onLoaded={refresh} />
      <ClockRow />
      <Ingest on={status.ingest_configured} />
      <Readings status={status} />
      <SpaceEvents />
    </>
  )
}

/* ---------------------------------------------------------------- mission package */
function Package({ status, onLoaded }: { status: DataStatus; onLoaded: () => void }) {
  const { bump } = useSession()
  const [result, setResult] = useState<{ text: string } | null>(null)
  const [rowErrors, setRowErrors] = useState<FieldIssue[]>([])
  const file = useRef<HTMLInputElement>(null)

  /** An import that the server refused names rows; those are listed, not forced onto a field. */
  const run = async (what: Parameters<typeof api.controlImport>[0], own: string[]) => {
    setResult(null); setRowErrors([])
    try {
      const r = await api.controlImport(what)
      setResult({ text: loaded(r) })
      bump(); onLoaded()
    } catch (e) {
      if (e instanceof ApiError && e.issues.length && !e.issues.every(i => own.includes(i.field))) { setRowErrors(e.issues); return }
      throw e
    }
  }

  const pkg = useForm({
    initial: { package: 'odyssey1-mars' },
    validate: f => ({ package: v.oneOf('Package', BUNDLED.map(b => b[0]))(f.package) }),
    submit: f => run({ package: f.package }, ['package']),
  })
  const up = useForm<{ files: File[] }>({
    initial: { files: [] },
    validate: f => ({ files: uploadError(f.files) }),
    submit: async f => { await run({ files: f.files }, ['file']); up.reset(); if (file.current) file.current.value = '' },
    mapField: field => (field === 'file' ? 'files' : field),
  })

  return (
    <section className="set-group rise">
      <div className="section-head"><h2>Mission package</h2><span className="sub">{status.package ? `Loaded: ${status.package}` : 'No package loaded'} · {status.counts.observations} readings, {status.counts.goal_entries} goal entries, {status.counts.events} events, {status.counts.scenes} scenes</span></div>
      <form className="set-row ctl-data-row" noValidate onSubmit={pkg.submit}>
        <div className="grow"><b>Load a bundled package</b><p className="small muted">Adds the people, plan, readings, goal history, events and scenes of a bundled mission. Readings already stored are not stored twice.</p></div>
        <Field form={pkg} name="package" label="Package" as="select">{BUNDLED.map(([k, n]) => <option key={k} value={k}>{n}</option>)}</Field>
        <SubmitButton form={pkg} busyLabel="Loading…" className="btn">Load package</SubmitButton>
      </form>
      <FormError form={pkg} />
      <form className="set-row ctl-data-row" noValidate onSubmit={up.submit}>
        <div className="grow"><b>Upload your own</b><p className="small muted">One .zip, or CSV files named like the package files (mission.csv, crew.csv, observations.csv, goal_log.csv, space_events.csv, scenes.csv). Nothing is written if any row is wrong.</p></div>
        <FieldGroup form={up} name="files" label="Files">
          <input ref={file} type="file" multiple accept=".zip,.csv,text/csv,application/zip" aria-label="Files to upload" className="in"
            onChange={e => { up.set('files', Array.from(e.target.files ?? [])); up.touch('files') }} />
        </FieldGroup>
        <SubmitButton form={up} busyLabel="Loading…" className="btn">Upload and load</SubmitButton>
      </form>
      <FormError form={up} />
      {result && <p className="small ok-text" role="status">{result.text}</p>}
      {rowErrors.length > 0 && (
        <div className="form-summary" role="alert">
          <b>Nothing was loaded: {rowErrors.length === 1 ? '1 problem' : `${rowErrors.length} problems`}</b>
          <ul>{rowErrors.slice(0, SHOWN_ERRORS).map((e, i) => <li key={i}>{e.field !== 'form' && <span className="num">{e.field}: </span>}{e.message}</li>)}</ul>
          {rowErrors.length > SHOWN_ERRORS && <p className="small dim">and {rowErrors.length - SHOWN_ERRORS} more</p>}
        </div>
      )}
    </section>
  )
}

/** What is wrong with the files chosen, or null. */
function uploadError(files: File[]): string | null {
  if (!files.length) return 'Choose a .zip or one or more .csv files'
  const names = files.map(f => f.name.toLowerCase())
  if (names.some(n => !n.endsWith('.zip') && !n.endsWith('.csv'))) return 'Only a .zip or .csv files can be loaded'
  if (names.some(n => n.endsWith('.zip')) && files.length > 1) return 'Send one .zip on its own, or CSV files without a zip'
  const big = files.find(f => f.size > MAX_UPLOAD_MB * 1024 * 1024)
  return big ? `${big.name} is ${(big.size / 1048576).toFixed(0)} MB; the limit is ${MAX_UPLOAD_MB} MB` : null
}

/* ---------------------------------------------------------------- mission clock */
function ClockRow() {
  const { mission, setMission, bump } = useSession()
  const clock = mission?.clock
  const form = useForm({
    initial: { date: clock?.date ?? '', time: clock?.time ?? '12:00' },
    validate: f => ({ date: v.date('Date', { minYear: 1990, maxYear: 2200 })(f.date), time: v.time('Time')(f.time) }),
    submit: async f => { setMission(await api.controlSetClock({ date: f.date, time: f.time })); bump() },
  })
  const real = useAction()
  if (!clock) return null
  return (
    <section className="set-group rise" style={{ ['--d' as string]: 1 }}>
      <div className="section-head"><h2>Mission clock</h2><span className="sub">{clock.mode === 'simulated' ? 'Simulated' : 'Real'} · {clockDate(clock.date)}, {clock.time}</span></div>
      <form className="set-row ctl-data-row" noValidate onSubmit={form.submit}>
        <div className="grow"><b>Set the date</b><p className="small muted">Mission day is this date minus the launch date. {mission ? `Now ${mission.day_label}, ${clockLine(clock)}.` : ''}</p></div>
        <Field form={form} name="date" label="Date" type="date" hint="1990 to 2200" />
        <Field form={form} name="time" label="Time" type="time" hint="24 hours" />
        <SubmitButton form={form} className="btn">Set the clock</SubmitButton>
      </form>
      <FormError form={form} />
      <div className="set-row">
        <div className="grow"><b>Use the real date</b><p className="small muted">The mission follows today's date in UTC.</p></div>
        <button type="button" className="btn" disabled={real.busy || clock.mode === 'real'} onClick={() => real.run(async () => { setMission(await api.controlSetClock({ real: true })); bump() })}>{real.busy ? 'Saving…' : 'Use real date'}</button>
      </div>
      <ActionError error={real.error} />
    </section>
  )
}

/* ---------------------------------------------------------------- ingest */
function Ingest({ on }: { on: boolean }) {
  return (
    <section className="set-group rise" style={{ ['--d' as string]: 2 }}>
      <div className="section-head"><h2>Sensor ingest</h2></div>
      <div className="set-row">
        <div className="grow">
          <b>{on ? 'Sensor ingest is configured' : 'Sensor ingest is off (set CANARY_INGEST_KEY)'}</b>
          <p className="small muted">{on ? 'Sensors, wearables and labs send readings to POST /api/observations with the key in the X-Canary-Key header. The key is never shown here.' : 'Readings can still arrive through a mission package.'}</p>
        </div>
      </div>
    </section>
  )
}

/* ---------------------------------------------------------------- readings received: dates and counts, never values */
function Readings({ status }: { status: DataStatus }) {
  const { catalog } = useSession()
  const people = [...new Set(status.readings.map(r => r.crew_id))]
  return (
    <section className="set-group rise" style={{ ['--d' as string]: 3 }}>
      <div className="section-head"><h2>Readings received</h2><span className="sub">When the last one arrived and how many, per person and indicator. Values stay with the person and the medical team.</span></div>
      {people.length === 0 && <p className="muted">No readings received yet.</p>}
      {people.map(id => (
        <details key={id} className="how">
          <summary>{id === 'cabin' ? 'Cabin sensors' : catalog?.crew.find(c => c.id === id)?.name ?? id} · {status.readings.filter(r => r.crew_id === id).reduce((s, r) => s + r.count, 0)} readings</summary>
          <div className="scroll"><table className="t">
            <thead><tr><th>Indicator</th><th>Last received</th><th>Mission day</th><th className="num">Count</th></tr></thead>
            <tbody>{status.readings.filter(r => r.crew_id === id).map(r => (
              <tr key={r.indicator}>
                <td>{catalog?.indicators[r.indicator]?.name ?? r.indicator}</td>
                <td className="num">{r.last_received_at.slice(0, 10)}</td>
                <td className="num">day {r.last_day}</td>
                <td className="num">{r.count}</td>
              </tr>
            ))}</tbody>
          </table></div>
        </details>
      ))}
    </section>
  )
}

/* ---------------------------------------------------------------- space weather events */
const KINDS: [string, string][] = [['sep', 'Solar particle event'], ['mars', 'Mars surface radiation event']]
const ORIGINS: [string, string][] = [['simulated', 'Simulated'], ['real', 'Real']]
const kindName = (k: string) => KINDS.find(x => x[0] === k)?.[1] ?? k

function SpaceEvents() {
  const { catalog, bump } = useSession()
  const { data, setData } = useApi<{ events: SpaceEvent[] }>(() => api.controlSpaceEvents(), [])
  const places = catalog?.locations ?? {}
  const form = useForm({
    initial: { kind: 'sep', start_day: '', end_day: '', locations: [] as string[], extra_dose_msv: '0', origin: 'simulated', note: '' },
    validate: f => {
      const start = v.number('Start day', { min: -3650, max: 36500, integer: true, unit: 'day' })(f.start_day)
      const end = v.number('End day', { min: -3650, max: 36500, integer: true, unit: 'day', optional: true })(f.end_day)
      const order = !start && !end && f.end_day.trim() && Number(f.end_day) < Number(f.start_day) ? 'End day must not be before the start day' : null
      return {
        kind: v.oneOf('Kind', KINDS.map(k => k[0]))(f.kind),
        start_day: start, end_day: end ?? order,
        locations: f.locations.length ? null : 'Choose at least one place',
        extra_dose_msv: v.number('Extra dose', { min: 0, max: 2000, unit: 'mSv', decimals: 1 })(f.extra_dose_msv),
        origin: v.oneOf('Origin', ORIGINS.map(o => o[0]))(f.origin),
        note: v.length('Note', { max: 200, optional: true })(f.note),
      }
    },
    submit: async f => {
      await api.controlAddSpaceEvent({ kind: f.kind, start_day: Number(f.start_day), end_day: f.end_day.trim() ? Number(f.end_day) : Number(f.start_day),
        locations: f.locations, extra_dose_msv: v.parseNumber(f.extra_dose_msv) ?? 0, origin: f.origin, ...(f.note.trim() ? { note: f.note.trim() } : {}) })
      setData(await api.controlSpaceEvents()); bump()
      form.reset()
    },
    mapField: field => field.replace(/^event\./, ''),
  })
  const toggle = (id: string) => form.set('locations', form.values.locations.includes(id) ? form.values.locations.filter(x => x !== id) : [...form.values.locations, id])
  return (
    <section className="set-group rise" style={{ ['--d' as string]: 4 }}>
      <div className="section-head"><h2>Space weather events</h2><span className="sub">Storms and surface radiation events that add dose. They also come from the mission package.</span></div>
      {!data ? <Loading what="events" /> : data.events.length === 0 ? <p className="muted">No events.</p> : (
        <div className="scroll"><table className="t">
          <thead><tr><th>Kind</th><th>Days</th><th>Places</th><th className="num">Extra dose</th><th>Origin</th></tr></thead>
          <tbody>{data.events.map(e => (
            <tr key={e.id}>
              <td>{kindName(e.kind)}</td>
              <td className="num">{e.start_day === e.end_day ? `day ${e.start_day}` : `day ${e.start_day} to ${e.end_day}`}</td>
              <td>{e.locations.map(l => places[l]?.name ?? l).join(', ')}</td>
              <td className="num">{e.extra_dose_msv} mSv</td>
              <td>{e.origin}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      <form className="col" style={{ gap: 12, marginTop: 18 }} noValidate onSubmit={form.submit}>
        <h3 className="sub-h">Add event</h3>
        <div className="form-grid">
          <Field form={form} name="kind" label="Kind" as="select">{KINDS.map(([k, n]) => <option key={k} value={k}>{n}</option>)}</Field>
          <Field form={form} name="start_day" label="Start day" inputMode="numeric" autoComplete="off" hint="Mission day, whole number" />
          <Field form={form} name="end_day" label="End day" optional inputMode="numeric" autoComplete="off" hint="Empty: the same day" />
          <Field form={form} name="extra_dose_msv" label="Extra dose (mSv)" inputMode="decimal" autoComplete="off" hint="0 to 2000 mSv" />
          <Field form={form} name="origin" label="Origin" as="select">{ORIGINS.map(([k, n]) => <option key={k} value={k}>{n}</option>)}</Field>
          <Field form={form} name="note" label="Note" optional maxLength={200} />
        </div>
        <FieldGroup form={form} name="locations" label="Places it reaches" hint="Choose at least one">
          <div className="row wrap" style={{ gap: 16 }}>
            {Object.entries(places).map(([id, p]) => (
              <label key={id} className="row" style={{ gap: 8 }}><input type="checkbox" checked={form.values.locations.includes(id)} onChange={() => toggle(id)} />{p.name}</label>
            ))}
          </div>
        </FieldGroup>
        <FormError form={form} />
        <SubmitButton form={form} className="btn pri start">Add event</SubmitButton>
      </form>
    </section>
  )
}
