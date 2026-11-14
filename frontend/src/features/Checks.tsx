// Self-tests and logs. Quick checks (reaction, mood, Amsler, vitals) also open from My space;
// the full set lives on the Tests page. Results are private: the person and the medical team.
import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { CheckinResult } from '../api/types'
import { ActionError, Field, FieldGroup, FormError, SubmitButton } from '../components/Field'
import { Icon } from '../components/ui'
import { fitJpeg } from '../lib/image'
import { useAction } from '../lib/useAction'
import { useForm, type FormApi } from '../lib/useForm'
import * as v from '../lib/validate'
import { useSession } from '../state/session'

export type CheckKind = 'pvt' | 'mood' | 'amsler' | 'vitals' | 'dsst' | 'span' | 'kss' | 'tlx' | 'wellbeing' | 'symptoms' | 'sleep' | 'reading' | 'journal'

export const CHECK_TITLE: Record<CheckKind, string> = {
  pvt: 'Reaction time', mood: 'Mood and stress', amsler: 'Vision (Amsler grid)', vitals: 'Vital signs', dsst: 'Processing speed', span: 'Working memory',
  kss: 'Sleepiness', tlx: 'Workload', wellbeing: 'Wellbeing', symptoms: 'Symptoms', sleep: 'Sleep diary', reading: 'Reading', journal: 'Journal',
}

const ResultCtx = createContext<(r: Saved) => void>(() => {})
interface Saved { r: CheckinResult; note?: string }

export default function Check({ kind, onClose }: { kind: CheckKind; onClose: () => void }) {
  // After a successful save the form is replaced by a short result step: no long toast.
  const [saved, setSaved] = useState<Saved | null>(null)
  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2>{CHECK_TITLE[kind]}</h2>
          <button className="btn sm ghost right" onClick={onClose}><Icon name="close" size={15} /></button>
        </div>
        {saved ? <Result saved={saved} onDone={onClose} /> : (
          <ResultCtx.Provider value={setSaved}>
            {kind === 'pvt' && <Pvt />}
            {kind === 'mood' && <Mood />}
            {kind === 'amsler' && <Amsler />}
            {kind === 'vitals' && <Vitals />}
            {kind === 'dsst' && <Dsst />}
            {kind === 'span' && <Span />}
            {kind === 'kss' && <Kss />}
            {kind === 'tlx' && <Tlx />}
            {kind === 'wellbeing' && <Wellbeing />}
            {kind === 'symptoms' && <Symptoms />}
            {kind === 'sleep' && <SleepLog />}
            {kind === 'reading' && <Reading />}
            {kind === 'journal' && <Journal />}
          </ResultCtx.Provider>
        )}
      </div>
    </div>
  )
}

/** What the save means: the summary, how it compares with your own normal and the population range, and any goal it completed. */
function Result({ saved: { r, note }, onDone }: { saved: Saved; onDone: () => void }) {
  return (
    <div className="col check-result" style={{ gap: 12 }} role="status">
      <p className="result-sum">{r.summary}</p>
      {note && <p className="muted">{note}</p>}
      {r.conclusion && <p>{r.conclusion.text}</p>}
      {r.goal && <p className="small" style={{ color: 'var(--ok)' }}>A goal for today is complete.</p>}
      <button className="btn pri" autoFocus onClick={onDone}>Done</button>
    </div>
  )
}

/** Sends one result. It throws when the server refuses it: the caller (a form or useSave) shows the message. On success the modal shows the result step. */
function useSubmit() {
  const { me, bump } = useSession()
  const show = useContext(ResultCtx)
  return async (kind: CheckKind, payload: Record<string, unknown>, note?: string, photo?: string) => {
    if (!me) throw new Error('Enter your PIN in My space first.')
    const r = await api.checkin(me, kind, payload, photo)
    bump(); show({ r, note })
  }
}

/** For results sent with one button (no typed input): catches a refusal and keeps its message next to the button. */
function useSave() {
  const submit = useSubmit()
  const a = useAction()
  return { save: (kind: CheckKind, payload: Record<string, unknown>, msg?: string) => a.run(() => submit(kind, payload, msg)), busy: a.busy, error: a.error }
}

function Pvt() {
  const { save, busy, error } = useSave()
  const [st, setSt] = useState<'idle' | 'wait' | 'go' | 'early'>('idle')
  const [rts, setRts] = useState<number[]>([])
  const t0 = useRef(0), tm = useRef<number>()
  useEffect(() => () => clearTimeout(tm.current), [])
  const tap = () => {
    if (st === 'go') { const rt = Math.round(performance.now() - t0.current); setRts(x => [...x, rt]); setSt('idle'); return }
    if (st === 'wait') { clearTimeout(tm.current); setSt('early'); return }
    setSt('wait')
    tm.current = window.setTimeout(() => { t0.current = performance.now(); setSt('go') }, 1200 + Math.random() * 2600)
  }
  const avg = rts.length ? Math.round(rts.reduce((a, b) => a + b) / rts.length) : 0
  return (
    <div className="col">
      <p className="muted">Tap the box the moment it turns red. Five rounds. It measures the tiredness you do not feel.</p>
      {rts.length < 5 ? (
        <div className={`pvt ${st === 'go' ? 'go' : ''}`} onPointerDown={tap} role="button" tabIndex={0}>
          {st === 'idle' ? (rts.length ? `${rts[rts.length - 1]} ms · tap for the next` : 'Tap to start') : st === 'wait' ? 'Wait…' : st === 'go' ? 'NOW' : 'Too early. Tap to retry'}
        </div>
      ) : (
        <div className="card pad-sm"><span className="lbl">Average</span><b className="num" style={{ fontSize: 36, display: 'block' }}>{avg} ms</b>
          <p className="small muted">On a normal screen this includes device lag. On board, the baseline is measured on the same terminal.</p></div>
      )}
      <div className="row wrap">{rts.map((r, i) => <span key={i} className="tag num">{r} ms</span>)}</div>
      {rts.length >= 5 && <button className="btn pri" disabled={busy} onClick={() => save('pvt', { ms: avg, rounds: rts })}>{busy ? 'Saving…' : 'Save result'}</button>}
      <ActionError error={error} />
    </div>
  )
}

function Scale5({ form, name, label, hint }: { form: FormApi; name: string; label: string; hint: string }) {
  return (
    <FieldGroup form={form} name={name} label={label} hint={hint}>
      <div className="scale5">{[1, 2, 3, 4, 5].map(n => <button type="button" key={n} className={form.values[name] === n ? 'on' : ''} aria-pressed={form.values[name] === n} onClick={() => form.set(name, n)}>{n}</button>)}</div>
    </FieldGroup>
  )
}

function Mood() {
  const submit = useSubmit()
  const form = useForm({
    initial: { mood: 0, stress: 0 },
    validate: f => ({ mood: f.mood ? null : 'Pick your mood, from 1 (low) to 5 (great)', stress: f.stress ? null : 'Pick your stress, from 1 (calm) to 5 (very)' }),
    submit: f => submit('mood', f, 'Thank you for being honest. A hard day counts the same as a good one.'),
  })
  return (
    <form className="col" style={{ gap: 14 }} noValidate onSubmit={form.submit}>
      <p className="muted">Thirty seconds. Only you and the medical team see it. A hard day counts the same as a good one.</p>
      <Scale5 form={form} name="mood" label="How is your mood?" hint="1 low, 5 great" />
      <Scale5 form={form} name="stress" label="How stressed are you?" hint="1 calm, 5 very" />
      <FormError form={form} />
      <SubmitButton form={form}>Send check-in</SubmitButton>
    </form>
  )
}

function Amsler() {
  const { save, busy, error } = useSave()
  return (
    <div className="col">
      <p className="muted">Cover one eye. Look only at the centre dot from 30 cm. Do any lines look wavy, blurred or missing?</p>
      <div className="amsler" aria-label="Amsler grid">{Array.from({ length: 400 }).map((_, i) => <i key={i} />)}</div>
      <div className="yesno">
        <button className="n" disabled={busy} onClick={() => save('amsler', { distortion: true }, 'The medical officer will be told.')}>Yes, distorted</button>
        <button className="y" disabled={busy} onClick={() => save('amsler', { distortion: false }, 'The grid looks clear.')}>No, all straight</button>
      </div>
      <ActionError error={error} />
    </div>
  )
}

const VITALS = [
  { k: 'hr', label: 'Pulse', unit: 'bpm', min: 25, max: 250 },
  { k: 'bp', label: 'Systolic pressure', unit: 'mmHg', min: 60, max: 260 },
  { k: 'temp', label: 'Temperature', unit: '°C', min: 30, max: 45, decimals: 1 },
  { k: 'spo2', label: 'Oxygen', unit: '%', min: 50, max: 100, integer: true },
] as const

const PHOTO_CAP = 580_000 // characters of the data URL; the server refuses more than 600 000

function Vitals() {
  const submit = useSubmit()
  const file = useRef<HTMLInputElement>(null)
  const [photoErr, setPhotoErr] = useState<string | null>(null)
  const [reading, setReading] = useState(false)
  const form = useForm({
    initial: { hr: '', bp: '', temp: '', spo2: '', photo: '' },
    validate: f => {
      const e: Record<string, string | null> = {}
      for (const { k, label, unit, min, max, ...o } of VITALS) e[k] = v.number(label, { min, max, unit, optional: true, ...o })(f[k])
      if (VITALS.every(({ k }) => !f[k].trim())) e.form = 'Type at least one value'
      return e
    },
    submit: f => submit('vitals', Object.fromEntries(VITALS.map(({ k }) => [k, f[k].trim() ? v.parseNumber(f[k]) : null])), undefined, f.photo || undefined),
  })
  const pick = async (f?: File) => {
    if (!f) return
    const bad = v.imageFile(f)
    if (bad) { setPhotoErr(bad); return }
    setPhotoErr(null); setReading(true)
    try {
      // Long edge at most 1024 px; if a busy picture is still big, once more smaller.
      let url = await fitJpeg(f, 1024, 0.8)
      if (url.length > PHOTO_CAP) url = await fitJpeg(f, 800, 0.6)
      if (url.length > PHOTO_CAP) { setPhotoErr('That photo is too detailed to keep. Take it again, closer to the display.'); return }
      form.set('photo', url)
    } catch { setPhotoErr('That file could not be read as an image. Pick another photo.') } finally { setReading(false) }
  }
  const photo = form.values.photo
  const err = photoErr ?? form.error('photo')
  return (
    <form className="col" style={{ gap: 12 }} noValidate onSubmit={form.submit}>
      <p className="muted">From the on-board device, or type them in. Empty fields keep the sensor value.</p>
      <div className="grid g2">
        {VITALS.map(({ k, label, unit, min, max, ...o }) => (
          <Field key={k} form={form} name={k} label={`${label} (${unit})`} hint={`${v.range(min, max, unit)}${'decimals' in o ? ', one decimal' : 'integer' in o ? ', whole number' : ''}`} inputMode="decimal" autoComplete="off" />
        ))}
      </div>
      <div className="field">
        <span className="lbl">Photo of the display<span className="dim"> (optional)</span></span>
        <input ref={file} type="file" accept="image/*" capture="environment" hidden aria-label="Add a photo of the display" onChange={e => { pick(e.target.files?.[0]); e.target.value = '' }} />
        {photo ? (
          <div className="photo-pick">
            <img src={photo} alt="The display you photographed" />
            <button type="button" className="btn sm ghost" onClick={() => { form.set('photo', ''); setPhotoErr(null) }}>Remove</button>
          </div>
        ) : (
          <div><button type="button" className="btn sm" disabled={reading} onClick={() => file.current?.click()}>{reading ? 'Reading…' : 'Add a photo of the display'}</button></div>
        )}
        {err ? <span className="err" role="alert">{err}</span> : <span className="hint">The photo is kept as evidence; the numbers you typed are what counts. Only you and the medical team can open it.</span>}
      </div>
      <FormError form={form} />
      <SubmitButton form={form}>Save</SubmitButton>
    </form>
  )
}

/* ---------- processing speed: digit symbol substitution, 60 seconds ---------- */
const GLYPHS = ['M4 4h16v16H4Z', 'M12 3 21 20H3Z', 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z', 'M3 12h18M12 3v18', 'M4 4l16 16M20 4 4 20',
  'M12 3v18M5 8h14M5 16h14', 'M4 20V4h16', 'M3 12c3-6 6-6 9 0s6 6 9 0', 'M12 3 21 12 12 21 3 12Z']
function Glyph({ i, size = 28 }: { i: number; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={GLYPHS[i]} /></svg>
}
function Dsst() {
  const { save, busy, error } = useSave()
  const [phase, setPhase] = useState<'idle' | 'run' | 'done'>('idle')
  const [target, setTarget] = useState(0)
  const [score, setScore] = useState({ correct: 0, errors: 0 })
  const [left, setLeft] = useState(60)
  const [flash, setFlash] = useState<'' | 'ok' | 'bad'>('')
  const next = () => setTarget(t => { let n = t; while (n === t) n = Math.floor(Math.random() * 9); return n })
  useEffect(() => {
    if (phase !== 'run') return
    const id = window.setInterval(() => setLeft(l => { if (l <= 1) { setPhase('done'); return 0 } return l - 1 }), 1000)
    return () => clearInterval(id)
  }, [phase])
  const answer = (d: number) => {
    if (phase !== 'run') return
    const ok = d === target + 1
    setScore(s => ({ correct: s.correct + (ok ? 1 : 0), errors: s.errors + (ok ? 0 : 1) }))
    setFlash(ok ? 'ok' : 'bad'); window.setTimeout(() => setFlash(''), 160)
    next()
  }
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (/^[1-9]$/.test(e.key)) answer(Number(e.key)) }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  })
  return (
    <div className="col" style={{ gap: 14 }}>
      <p className="muted">Each symbol has a number in the key. For 60 seconds, press the number of the symbol in the middle. Fast, but right.</p>
      <div className="dsst-key">{GLYPHS.map((_, i) => <div key={i}><Glyph i={i} size={22} /><b className="num">{i + 1}</b></div>)}</div>
      {phase === 'idle' && <button className="btn pri" onClick={() => { next(); setPhase('run') }}>Start, 60 seconds</button>}
      {phase === 'run' && (
        <>
          <div className={`dsst-target ${flash}`}><Glyph i={target} size={56} /><span className="num small muted">{left} s</span></div>
          <div className="dsst-pad">{Array.from({ length: 9 }, (_, i) => <button key={i} className="num" onClick={() => answer(i + 1)}>{i + 1}</button>)}</div>
        </>
      )}
      {phase === 'done' && (
        <>
          <div className="result-big"><b className="num">{score.correct}</b><span>correct, {score.errors} {score.errors === 1 ? 'error' : 'errors'}</span></div>
          <ActionError error={error} />
          <button className="btn pri" disabled={busy} onClick={() => save('dsst', score)}>{busy ? 'Saving…' : 'Save result'}</button>
        </>
      )}
    </div>
  )
}

/* ---------- working memory: forward digit span ---------- */
function Span() {
  const { save, busy, error } = useSave()
  const [len, setLen] = useState(3)
  const [seq, setSeq] = useState<number[]>([])
  const [shown, setShown] = useState(-1)
  const [phase, setPhase] = useState<'idle' | 'show' | 'answer' | 'done'>('idle')
  const [best, setBest] = useState(0)
  const [fails, setFails] = useState(0)
  const form = useForm({
    initial: { typed: '' },
    validate: f => ({ typed: f.typed.trim() ? null : `Type the ${len} digits you saw` }),
    submit: f => check(f.typed),
  })
  const play = (n: number) => {
    const s = Array.from({ length: n }, () => Math.floor(Math.random() * 10))
    setSeq(s); form.reset({ typed: '' }); setPhase('show'); setShown(0)
  }
  useEffect(() => {
    if (phase !== 'show') return
    if (shown >= seq.length) { setPhase('answer'); return }
    const id = window.setTimeout(() => setShown(x => x + 1), 900)
    return () => clearTimeout(id)
  }, [phase, shown, seq.length])
  const check = (typed: string) => {
    if (typed === seq.join('')) { setBest(len); setFails(0); setLen(len + 1); play(len + 1) }
    else if (fails >= 1 || len >= 12) setPhase('done')
    else { setFails(1); play(len) }
  }
  return (
    <div className="col" style={{ gap: 14 }}>
      <p className="muted">Digits appear one at a time. Type them back in the same order. Each round adds one. Two misses in a row end it.</p>
      {phase === 'idle' && <button className="btn pri" onClick={() => play(3)}>Start</button>}
      {phase === 'show' && <div className="span-digit num" key={shown}>{shown < seq.length ? seq[shown] : ''}</div>}
      {phase === 'answer' && (
        <form className="col" noValidate onSubmit={form.submit}>
          <Field form={form} name="typed" label={`${len} digits`} hint="Digits only" className="span-in" autoFocus inputMode="numeric" autoComplete="off" aria-label="Digits you saw" map={t => t.replace(/\D/g, '')} />
          <SubmitButton form={form} busyLabel="Checking…">Check</SubmitButton>
        </form>
      )}
      {phase === 'done' && (
        <>
          <div className="result-big"><b className="num">{best}</b><span>digits held in mind</span></div>
          <ActionError error={error} />
          <button className="btn pri" disabled={busy} onClick={() => save('span', { span: best })}>{busy ? 'Saving…' : 'Save result'}</button>
        </>
      )}
    </div>
  )
}

/* ---------- sleepiness: Karolinska Sleepiness Scale ---------- */
const KSS = ['Extremely alert', 'Very alert', 'Alert', 'Rather alert', 'Neither alert nor sleepy', 'Some signs of sleepiness',
  'Sleepy, but no effort to keep awake', 'Sleepy, some effort to keep awake', 'Very sleepy, great effort to keep awake, fighting sleep']
function Kss() {
  const { save, busy, error } = useSave()
  return (
    <div className="col" style={{ gap: 10 }}>
      <p className="muted">How sleepy are you right now, in the last 10 minutes?</p>
      <div className="scale-list">{KSS.map((t, i) => (
        <button key={i} disabled={busy} onClick={() => save('kss', { level: i + 1 })}><b className="num">{i + 1}</b><span>{t}</span></button>
      ))}</div>
      <ActionError error={error} />
    </div>
  )
}

/* ---------- workload: NASA-TLX (raw) ---------- */
const TLX: [string, string, string, string][] = [
  ['mental', 'Mental demand', 'How mentally demanding was the work?', 'Very low|Very high'],
  ['physical', 'Physical demand', 'How physically demanding was it?', 'Very low|Very high'],
  ['temporal', 'Time pressure', 'How hurried or rushed was the pace?', 'Very low|Very high'],
  ['performance', 'Performance', 'How successful were you at what you were asked to do?', 'Perfect|Failure'],
  ['effort', 'Effort', 'How hard did you have to work for that level of performance?', 'Very low|Very high'],
  ['frustration', 'Frustration', 'How insecure, discouraged, irritated or stressed were you?', 'Very low|Very high'],
]
function Tlx() {
  const { save, busy, error } = useSave()
  const [sc, setSc] = useState<Record<string, number>>(Object.fromEntries(TLX.map(([k]) => [k, 50])))
  return (
    <div className="col" style={{ gap: 16 }}>
      <p className="muted">Think about today's work. Slide each one.</p>
      {TLX.map(([k, name, q, anchors]) => {
        const [lo, hi] = anchors.split('|')
        return (
          <label key={k} className="col" style={{ gap: 4 }}>
            <span className="row"><b>{name}</b><span className="num small muted right">{sc[k]}</span></span>
            <span className="small muted">{q}</span>
            <input type="range" min={0} max={100} step={5} value={sc[k]} onChange={e => setSc({ ...sc, [k]: Number(e.target.value) })} />
            <span className="row small dim"><span>{lo}</span><span className="right">{hi}</span></span>
          </label>
        )
      })}
      <ActionError error={error} />
      <button className="btn pri" disabled={busy} onClick={() => save('tlx', { scores: sc })}>{busy ? 'Saving…' : 'Save'}</button>
    </div>
  )
}

/* ---------- wellbeing: PHQ-2 and GAD-2 ---------- */
const WB_Q = ['Little interest or pleasure in doing things', 'Feeling down, depressed or hopeless',
  'Feeling nervous, anxious or on edge', 'Not being able to stop or control worrying']
const WB_A = ['Not at all', 'Several days', 'More than half the days', 'Nearly every day']
function Wellbeing() {
  const submit = useSubmit()
  const form = useForm({
    initial: { q0: -1, q1: -1, q2: -1, q3: -1 } as Record<string, number>,
    validate: f => Object.fromEntries(WB_Q.map((q, i) => [`q${i}`, f[`q${i}`] >= 0 ? null : `Answer question ${i + 1}: ${q}`])),
    submit: f => submit('wellbeing', { answers: WB_Q.map((_, i) => f[`q${i}`]) }),
  })
  const a = WB_Q.map((_, i) => form.values[`q${i}`] as number)
  const flag = a.every(x => x >= 0) && (a[0] + a[1] >= 3 || a[2] + a[3] >= 3)
  return (
    <form className="col" style={{ gap: 14 }} noValidate onSubmit={form.submit}>
      <p className="muted">Over the last two weeks, how often have you been bothered by the following? Only you and the medical team see this.</p>
      {WB_Q.map((q, i) => (
        <FieldGroup key={i} form={form} name={`q${i}`} label={<b className="q">{q}</b>}>
          <div className="seg-ctl wrap">{WB_A.map((t, j) => <button type="button" key={j} className={a[i] === j ? 'on' : ''} aria-pressed={a[i] === j} onClick={() => form.set(`q${i}`, j)}>{t}</button>)}</div>
        </FieldGroup>
      ))}
      {flag && <p className="small" style={{ color: 'var(--watch)' }}>Thank you for answering honestly. This is worth talking about: Canary will suggest a moment with the medical officer.</p>}
      <FormError form={form} />
      <SubmitButton form={form}>Save</SubmitButton>
    </form>
  )
}

/* ---------- symptoms ---------- */
const SYMPTOMS = ['Headache', 'Congestion', 'Back pain', 'Nausea', 'Eye discomfort', 'Blurred vision', 'Skin irritation', 'Trouble sleeping', 'Muscle or joint pain', 'Dizziness']
function Symptoms() {
  const submit = useSubmit()
  const form = useForm({
    initial: { items: [] as string[], sev: 1, note: '' },
    validate: f => ({ note: v.length('Note', { max: 200, optional: true })(f.note) }),
    submit: f => submit('symptoms', { items: f.items, severity: f.items.length ? f.sev : 0, note: f.note.trim() }),
  })
  const { items, sev } = form.values
  return (
    <form className="col" style={{ gap: 14 }} noValidate onSubmit={form.submit}>
      <p className="muted">Tick anything you feel now. Leave it empty if all is well: that is useful too.</p>
      <div className="chips-pick">{SYMPTOMS.map(t => (
        <button type="button" key={t} className={items.includes(t) ? 'on' : ''} aria-pressed={items.includes(t)} onClick={() => form.set('items', items.includes(t) ? items.filter(y => y !== t) : [...items, t])}>{t}</button>
      ))}</div>
      {!!items.length && (
        <div className="col" style={{ gap: 6 }}>
          <b>How strong?</b>
          <div className="seg-ctl">{['Mild', 'Moderate', 'Strong'].map((t, i) => <button type="button" key={t} className={sev === i + 1 ? 'on' : ''} aria-pressed={sev === i + 1} onClick={() => form.set('sev', i + 1)}>{t}</button>)}</div>
        </div>
      )}
      <Field form={form} name="note" label="Anything else" optional hint="Up to 200 characters" maxLength={200} />
      <FormError form={form} />
      <SubmitButton form={form}>{items.length ? 'Save' : 'All well, save'}</SubmitButton>
    </form>
  )
}

/* ---------- logs ---------- */
function SleepLog() {
  const submit = useSubmit()
  const form = useForm({
    initial: { bed: '23:00', wake: '07:00', q: 0 },
    validate: f => {
      const e: Record<string, string | null> = { bed: v.time('Lights out')(f.bed), wake: v.time('Woke up')(f.wake), q: f.q ? null : 'Rate how well you slept, from 1 (badly) to 5 (very well)' }
      const h = v.sleepHours(f.bed, f.wake)
      if (!e.wake && !e.bed && h !== null && (h < 1 || h > 16)) e.wake = `Sleep must last between 1 and 16 h (these times give ${h} h)`
      return e
    },
    submit: f => submit('sleep', { bed: f.bed, wake: f.wake, quality: f.q }),
  })
  return (
    <form className="col" style={{ gap: 14 }} noValidate onSubmit={form.submit}>
      <p className="muted">Last night. It feeds your sleep reading for today.</p>
      <div className="grid g2">
        <Field form={form} name="bed" label="Lights out" type="time" hint="24-hour time" />
        <Field form={form} name="wake" label="Woke up" type="time" hint="Sleep of 1 to 16 h" />
      </div>
      <Scale5 form={form} name="q" label="How well did you sleep?" hint="1 badly, 5 very well" />
      <FormError form={form} />
      <SubmitButton form={form}>Save</SubmitButton>
    </form>
  )
}

function Reading() {
  const submit = useSubmit()
  const form = useForm({
    initial: { title: '', minutes: '20', pages: '', enjoy: 0 },
    validate: f => ({
      title: v.length('Title', { max: 120 })(f.title),
      minutes: v.number('Minutes', { min: 1, max: 600, unit: 'min', integer: true })(f.minutes),
      pages: v.number('Pages', { min: 0, max: 2000, integer: true, optional: true })(f.pages),
    }),
    submit: f => submit('reading', { title: f.title.trim(), minutes: Number(f.minutes), pages: f.pages.trim() ? Number(f.pages) : null, absorbing: f.enjoy || null }),
  })
  return (
    <form className="col" style={{ gap: 14 }} noValidate onSubmit={form.submit}>
      <p className="muted">Deep attention on something that is not the mission. Twenty minutes completes today's reading goal.</p>
      <Field form={form} name="title" label="Book" placeholder="Title" maxLength={120} />
      <div className="grid g2">
        <Field form={form} name="minutes" label="Minutes" hint={v.range(1, 600, 'min')} inputMode="numeric" />
        <Field form={form} name="pages" label="Pages" optional hint={v.range(0, 2000, 'pages')} inputMode="numeric" />
      </div>
      <FieldGroup form={form} name="enjoy" label="How absorbing was it? (optional)" hint="1 not at all, 5 completely">
        <div className="scale5">{[1, 2, 3, 4, 5].map(n => <button type="button" key={n} className={form.values.enjoy === n ? 'on' : ''} aria-pressed={form.values.enjoy === n} onClick={() => form.set('enjoy', n)}>{n}</button>)}</div>
      </FieldGroup>
      <FormError form={form} />
      <SubmitButton form={form}>Save</SubmitButton>
    </form>
  )
}

function Journal() {
  const submit = useSubmit()
  const PH = ['Something that happened', 'How it felt', 'Something you are looking forward to']
  const form = useForm({
    initial: { l0: '', l1: '', l2: '' } as Record<string, string>,
    validate: f => {
      const e: Record<string, string | null> = {}
      PH.forEach((_, i) => { e[`l${i}`] = v.length('This line', { max: 200, optional: true })(f[`l${i}`]) })
      if (!PH.some((_, i) => f[`l${i}`].trim())) e.l0 = 'Write at least one line'
      return e
    },
    submit: f => submit('journal', { lines: PH.filter((_, i) => f[`l${i}`].trim()).length }, 'Your words were not saved: Canary only records that you wrote.'),
  })
  return (
    <form className="col" style={{ gap: 12 }} noValidate onSubmit={form.submit}>
      <p className="muted">Three lines about today. They stay on this screen: Canary only records that you wrote.</p>
      {PH.map((ph, i) => <Field key={i} form={form} name={`l${i}`} label={ph} maxLength={200} />)}
      <FormError form={form} />
      <SubmitButton form={form} busyLabel="Saving…">Done</SubmitButton>
    </form>
  )
}
