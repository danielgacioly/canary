// Self-tests and logs. Quick checks (reaction, mood, Amsler, vitals) also open from My space;
// the full set lives on the Tests page. Results are private: the person and the medical team.
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { Icon } from '../components/ui'
import { useSession } from '../state/session'

export type CheckKind = 'pvt' | 'mood' | 'amsler' | 'vitals' | 'dsst' | 'span' | 'kss' | 'tlx' | 'wellbeing' | 'symptoms' | 'sleep' | 'reading' | 'journal'

export const CHECK_TITLE: Record<CheckKind, string> = {
  pvt: 'Reaction time', mood: 'Mood and stress', amsler: 'Vision (Amsler grid)', vitals: 'Vital signs', dsst: 'Processing speed', span: 'Working memory',
  kss: 'Sleepiness', tlx: 'Workload', wellbeing: 'Wellbeing', symptoms: 'Symptoms', sleep: 'Sleep diary', reading: 'Reading', journal: 'Journal',
}

export default function Check({ kind, onClose }: { kind: CheckKind; onClose: () => void }) {
  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2>{CHECK_TITLE[kind]}</h2>
          <button className="btn sm ghost right" onClick={onClose}><Icon name="close" size={15} /></button>
        </div>
        {kind === 'pvt' && <Pvt onClose={onClose} />}
        {kind === 'mood' && <Mood onClose={onClose} />}
        {kind === 'amsler' && <Amsler onClose={onClose} />}
        {kind === 'vitals' && <Vitals onClose={onClose} />}
        {kind === 'dsst' && <Dsst onClose={onClose} />}
        {kind === 'span' && <Span onClose={onClose} />}
        {kind === 'kss' && <Kss onClose={onClose} />}
        {kind === 'tlx' && <Tlx onClose={onClose} />}
        {kind === 'wellbeing' && <Wellbeing onClose={onClose} />}
        {kind === 'symptoms' && <Symptoms onClose={onClose} />}
        {kind === 'sleep' && <SleepLog onClose={onClose} />}
        {kind === 'reading' && <Reading onClose={onClose} />}
        {kind === 'journal' && <Journal onClose={onClose} />}
      </div>
    </div>
  )
}

function useSubmit(onClose: () => void) {
  const { me, bump, toast } = useSession()
  return async (kind: CheckKind, payload: Record<string, unknown>, msg?: string) => {
    if (!me) return
    const r = await api.checkin(me, kind, payload)
    bump(); toast(msg ?? `Saved: ${r.summary}${r.goal ? ' · goal done' : ''}`); onClose()
  }
}

function Pvt({ onClose }: { onClose: () => void }) {
  const submit = useSubmit(onClose)
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
      {rts.length >= 5 && <button className="btn pri" onClick={() => submit('pvt', { ms: avg, rounds: rts }, `Reaction test saved: ${avg} ms`)}>Save result</button>}
    </div>
  )
}

function Mood({ onClose }: { onClose: () => void }) {
  const submit = useSubmit(onClose)
  const [mood, setMood] = useState(0), [stress, setStress] = useState(0)
  return (
    <div className="col" style={{ gap: 14 }}>
      <p className="muted">Thirty seconds. Only you and the medical team see it. A hard day counts the same as a good one.</p>
      <span className="lbl">How is your mood? (1 low, 5 great)</span>
      <div className="scale5">{[1, 2, 3, 4, 5].map(n => <button key={n} className={mood === n ? 'on' : ''} onClick={() => setMood(n)}>{n}</button>)}</div>
      <span className="lbl">How stressed are you? (1 calm, 5 very)</span>
      <div className="scale5">{[1, 2, 3, 4, 5].map(n => <button key={n} className={stress === n ? 'on' : ''} onClick={() => setStress(n)}>{n}</button>)}</div>
      <button className="btn pri" disabled={!mood || !stress} onClick={() => submit('mood', { mood, stress }, 'Check-in sent. Thank you for being honest.')}>Send check-in</button>
    </div>
  )
}

function Amsler({ onClose }: { onClose: () => void }) {
  const submit = useSubmit(onClose)
  return (
    <div className="col">
      <p className="muted">Cover one eye. Look only at the centre dot from 30 cm. Do any lines look wavy, blurred or missing?</p>
      <div className="amsler" aria-label="Amsler grid">{Array.from({ length: 400 }).map((_, i) => <i key={i} />)}</div>
      <div className="yesno">
        <button className="n" onClick={() => submit('amsler', { distortion: true }, 'Saved. The medical officer will be told.')}>Yes, distorted</button>
        <button className="y" onClick={() => submit('amsler', { distortion: false }, 'Saved: grid looks clear.')}>No, all straight</button>
      </div>
    </div>
  )
}

function Vitals({ onClose }: { onClose: () => void }) {
  const submit = useSubmit(onClose)
  const [v, setV] = useState({ hr: '', bp: '', temp: '', spo2: '' })
  const f = (k: keyof typeof v, label: string, unit: string) => (
    <label className="col" style={{ gap: 4 }}><span className="lbl">{label} ({unit})</span>
      <input value={v[k]} onChange={e => setV({ ...v, [k]: e.target.value })} inputMode="decimal" style={{ padding: 10, borderRadius: 9, border: '1px solid var(--line-2)', background: 'var(--bg)' }} /></label>
  )
  const num = (s: string) => (s.trim() ? Number(s) : null)
  return (
    <div className="col" style={{ gap: 12 }}>
      <p className="muted">From the on-board device, or type them in. Empty fields keep the sensor value.</p>
      <div className="grid g2">{f('hr', 'Pulse', 'bpm')}{f('bp', 'Systolic pressure', 'mmHg')}{f('temp', 'Temperature', '°C')}{f('spo2', 'Oxygen', '%')}</div>
      <button className="btn pri" onClick={() => submit('vitals', { hr: num(v.hr), bp: num(v.bp), temp: num(v.temp), spo2: num(v.spo2) }, 'Vital signs saved.')}>Save</button>
    </div>
  )
}

const inputStyle = { padding: 10, borderRadius: 9, border: '1px solid var(--line-2)', background: 'var(--bg)' }

/* ---------- processing speed: digit symbol substitution, 60 seconds ---------- */
const GLYPHS = ['M4 4h16v16H4Z', 'M12 3 21 20H3Z', 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z', 'M3 12h18M12 3v18', 'M4 4l16 16M20 4 4 20',
  'M12 3v18M5 8h14M5 16h14', 'M4 20V4h16', 'M3 12c3-6 6-6 9 0s6 6 9 0', 'M12 3 21 12 12 21 3 12Z']
function Glyph({ i, size = 28 }: { i: number; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={GLYPHS[i]} /></svg>
}
function Dsst({ onClose }: { onClose: () => void }) {
  const submit = useSubmit(onClose)
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
          <button className="btn pri" onClick={() => submit('dsst', score)}>Save result</button>
        </>
      )}
    </div>
  )
}

/* ---------- working memory: forward digit span ---------- */
function Span({ onClose }: { onClose: () => void }) {
  const submit = useSubmit(onClose)
  const [len, setLen] = useState(3)
  const [seq, setSeq] = useState<number[]>([])
  const [shown, setShown] = useState(-1)
  const [phase, setPhase] = useState<'idle' | 'show' | 'answer' | 'done'>('idle')
  const [typed, setTyped] = useState('')
  const [best, setBest] = useState(0)
  const [fails, setFails] = useState(0)
  const play = (n: number) => {
    const s = Array.from({ length: n }, () => Math.floor(Math.random() * 10))
    setSeq(s); setTyped(''); setPhase('show'); setShown(0)
  }
  useEffect(() => {
    if (phase !== 'show') return
    if (shown >= seq.length) { setPhase('answer'); return }
    const id = window.setTimeout(() => setShown(x => x + 1), 900)
    return () => clearTimeout(id)
  }, [phase, shown, seq.length])
  const check = () => {
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
        <form className="col" onSubmit={e => { e.preventDefault(); check() }}>
          <span className="lbl">{len} digits</span>
          <input autoFocus inputMode="numeric" value={typed} onChange={e => setTyped(e.target.value.replace(/\D/g, ''))} style={{ ...inputStyle, font: '500 26px var(--f-mono)', letterSpacing: '.2em' }} aria-label="Digits you saw" />
          <button className="btn pri">Check</button>
        </form>
      )}
      {phase === 'done' && (
        <>
          <div className="result-big"><b className="num">{best}</b><span>digits held in mind</span></div>
          <button className="btn pri" onClick={() => submit('span', { span: best })}>Save result</button>
        </>
      )}
    </div>
  )
}

/* ---------- sleepiness: Karolinska Sleepiness Scale ---------- */
const KSS = ['Extremely alert', 'Very alert', 'Alert', 'Rather alert', 'Neither alert nor sleepy', 'Some signs of sleepiness',
  'Sleepy, but no effort to keep awake', 'Sleepy, some effort to keep awake', 'Very sleepy, great effort to keep awake, fighting sleep']
function Kss({ onClose }: { onClose: () => void }) {
  const submit = useSubmit(onClose)
  return (
    <div className="col" style={{ gap: 10 }}>
      <p className="muted">How sleepy are you right now, in the last 10 minutes?</p>
      <div className="scale-list">{KSS.map((t, i) => (
        <button key={i} onClick={() => submit('kss', { level: i + 1 })}><b className="num">{i + 1}</b><span>{t}</span></button>
      ))}</div>
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
function Tlx({ onClose }: { onClose: () => void }) {
  const submit = useSubmit(onClose)
  const [v, setV] = useState<Record<string, number>>(Object.fromEntries(TLX.map(([k]) => [k, 50])))
  return (
    <div className="col" style={{ gap: 16 }}>
      <p className="muted">Think about today's work. Slide each one.</p>
      {TLX.map(([k, name, q, anchors]) => {
        const [lo, hi] = anchors.split('|')
        return (
          <label key={k} className="col" style={{ gap: 4 }}>
            <span className="row"><b>{name}</b><span className="num small muted right">{v[k]}</span></span>
            <span className="small muted">{q}</span>
            <input type="range" min={0} max={100} step={5} value={v[k]} onChange={e => setV({ ...v, [k]: Number(e.target.value) })} />
            <span className="row small dim"><span>{lo}</span><span className="right">{hi}</span></span>
          </label>
        )
      })}
      <button className="btn pri" onClick={() => submit('tlx', { scores: v })}>Save</button>
    </div>
  )
}

/* ---------- wellbeing: PHQ-2 and GAD-2 ---------- */
const WB_Q = ['Little interest or pleasure in doing things', 'Feeling down, depressed or hopeless',
  'Feeling nervous, anxious or on edge', 'Not being able to stop or control worrying']
const WB_A = ['Not at all', 'Several days', 'More than half the days', 'Nearly every day']
function Wellbeing({ onClose }: { onClose: () => void }) {
  const submit = useSubmit(onClose)
  const [a, setA] = useState<number[]>([-1, -1, -1, -1])
  const ready = a.every(x => x >= 0)
  const flag = ready && (a[0] + a[1] >= 3 || a[2] + a[3] >= 3)
  return (
    <div className="col" style={{ gap: 14 }}>
      <p className="muted">Over the last two weeks, how often have you been bothered by the following? Only you and the medical team see this.</p>
      {WB_Q.map((q, i) => (
        <div key={i} className="col" style={{ gap: 6 }}>
          <b>{q}</b>
          <div className="seg-ctl wrap">{WB_A.map((t, j) => <button key={j} className={a[i] === j ? 'on' : ''} onClick={() => setA(x => x.map((y, k) => (k === i ? j : y)))}>{t}</button>)}</div>
        </div>
      ))}
      {flag && <p className="small" style={{ color: 'var(--watch)' }}>Thank you for answering honestly. This is worth talking about: Canary will suggest a moment with the medical officer.</p>}
      <button className="btn pri" disabled={!ready} onClick={() => submit('wellbeing', { answers: a })}>Save</button>
    </div>
  )
}

/* ---------- symptoms ---------- */
const SYMPTOMS = ['Headache', 'Congestion', 'Back pain', 'Nausea', 'Eye discomfort', 'Blurred vision', 'Skin irritation', 'Trouble sleeping', 'Muscle or joint pain', 'Dizziness']
function Symptoms({ onClose }: { onClose: () => void }) {
  const submit = useSubmit(onClose)
  const [items, setItems] = useState<string[]>([])
  const [sev, setSev] = useState(1)
  const [note, setNote] = useState('')
  return (
    <div className="col" style={{ gap: 14 }}>
      <p className="muted">Tick anything you feel now. Leave it empty if all is well: that is useful too.</p>
      <div className="chips-pick">{SYMPTOMS.map(t => (
        <button key={t} className={items.includes(t) ? 'on' : ''} onClick={() => setItems(x => (x.includes(t) ? x.filter(y => y !== t) : [...x, t]))}>{t}</button>
      ))}</div>
      {!!items.length && (
        <div className="col" style={{ gap: 6 }}>
          <b>How strong?</b>
          <div className="seg-ctl">{['Mild', 'Moderate', 'Strong'].map((t, i) => <button key={t} className={sev === i + 1 ? 'on' : ''} onClick={() => setSev(i + 1)}>{t}</button>)}</div>
        </div>
      )}
      <input placeholder="Anything else (optional)" value={note} onChange={e => setNote(e.target.value)} style={inputStyle} maxLength={200} />
      <button className="btn pri" onClick={() => submit('symptoms', { items, severity: items.length ? sev : 0, note })}>{items.length ? 'Save' : 'All well, save'}</button>
    </div>
  )
}

/* ---------- logs ---------- */
function SleepLog({ onClose }: { onClose: () => void }) {
  const submit = useSubmit(onClose)
  const [bed, setBed] = useState('23:00'), [wake, setWake] = useState('07:00'), [q, setQ] = useState(0)
  return (
    <div className="col" style={{ gap: 14 }}>
      <p className="muted">Last night. It feeds your sleep reading for today.</p>
      <div className="grid g2">
        <label className="col" style={{ gap: 4 }}><span className="lbl">Lights out</span><input type="time" value={bed} onChange={e => setBed(e.target.value)} style={inputStyle} /></label>
        <label className="col" style={{ gap: 4 }}><span className="lbl">Woke up</span><input type="time" value={wake} onChange={e => setWake(e.target.value)} style={inputStyle} /></label>
      </div>
      <span className="lbl">How well did you sleep? (1 badly, 5 very well)</span>
      <div className="scale5">{[1, 2, 3, 4, 5].map(n => <button key={n} className={q === n ? 'on' : ''} onClick={() => setQ(n)}>{n}</button>)}</div>
      <button className="btn pri" disabled={!q} onClick={() => submit('sleep', { bed, wake, quality: q })}>Save</button>
    </div>
  )
}

function Reading({ onClose }: { onClose: () => void }) {
  const submit = useSubmit(onClose)
  const [title, setTitle] = useState(''), [minutes, setMinutes] = useState('20'), [pages, setPages] = useState(''), [enjoy, setEnjoy] = useState(0)
  return (
    <div className="col" style={{ gap: 14 }}>
      <p className="muted">Deep attention on something that is not the mission. Twenty minutes completes today's reading goal.</p>
      <label className="col" style={{ gap: 4 }}><span className="lbl">Book</span><input value={title} onChange={e => setTitle(e.target.value)} placeholder="Title" style={inputStyle} maxLength={120} /></label>
      <div className="grid g2">
        <label className="col" style={{ gap: 4 }}><span className="lbl">Minutes</span><input inputMode="numeric" value={minutes} onChange={e => setMinutes(e.target.value.replace(/\D/g, ''))} style={inputStyle} /></label>
        <label className="col" style={{ gap: 4 }}><span className="lbl">Pages (optional)</span><input inputMode="numeric" value={pages} onChange={e => setPages(e.target.value.replace(/\D/g, ''))} style={inputStyle} /></label>
      </div>
      <span className="lbl">How absorbing was it? (1 not at all, 5 completely)</span>
      <div className="scale5">{[1, 2, 3, 4, 5].map(n => <button key={n} className={enjoy === n ? 'on' : ''} onClick={() => setEnjoy(n)}>{n}</button>)}</div>
      <button className="btn pri" disabled={!minutes} onClick={() => submit('reading', { title: title.trim(), minutes: Number(minutes), pages: pages ? Number(pages) : null, absorbing: enjoy || null })}>Save</button>
    </div>
  )
}

function Journal({ onClose }: { onClose: () => void }) {
  const submit = useSubmit(onClose)
  const [lines, setLines] = useState(['', '', ''])
  const n = lines.filter(l => l.trim()).length
  return (
    <div className="col" style={{ gap: 12 }}>
      <p className="muted">Three lines about today. They stay on this screen: Canary only records that you wrote.</p>
      {['Something that happened', 'How it felt', 'Something you are looking forward to'].map((ph, i) => (
        <input key={i} placeholder={ph} value={lines[i]} onChange={e => setLines(x => x.map((y, k) => (k === i ? e.target.value : y)))} style={inputStyle} maxLength={200} />
      ))}
      <button className="btn pri" disabled={!n} onClick={() => submit('journal', { lines: n }, 'Journal done. Your words were not saved.')}>Done</button>
    </div>
  )
}
