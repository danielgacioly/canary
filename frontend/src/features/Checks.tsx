// Self-checks that feed telemetry: reaction test (PVT), mood, Amsler grid and vital signs.
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { Icon } from '../components/ui'
import { useSession } from '../state/session'

export type CheckKind = 'pvt' | 'mood' | 'amsler' | 'vitals'

export default function Check({ kind, onClose }: { kind: CheckKind; onClose: () => void }) {
  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2>{{ pvt: 'Reaction test', mood: 'Mood check-in', amsler: 'Amsler grid', vitals: 'Vital signs' }[kind]}</h2>
          <button className="btn sm ghost right" onClick={onClose}><Icon name="close" size={15} /></button>
        </div>
        {kind === 'pvt' && <Pvt onClose={onClose} />}
        {kind === 'mood' && <Mood onClose={onClose} />}
        {kind === 'amsler' && <Amsler onClose={onClose} />}
        {kind === 'vitals' && <Vitals onClose={onClose} />}
      </div>
    </div>
  )
}

function useSubmit(onClose: () => void) {
  const { me, bump, toast } = useSession()
  return async (kind: CheckKind, payload: Record<string, unknown>, msg: string) => {
    if (!me) return
    await api.checkin(me, kind, payload)
    bump(); toast(msg); onClose()
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
        <div className="card flat"><span className="lbl">Average</span><b className="num" style={{ fontSize: 36, display: 'block' }}>{avg} ms</b>
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
      <p className="muted">Thirty seconds. Only you and the medical team see it. A hard day earns the same XP as a good one.</p>
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
      <input value={v[k]} onChange={e => setV({ ...v, [k]: e.target.value })} inputMode="decimal" style={{ padding: 10, borderRadius: 9, border: '1px solid var(--line-2)', background: 'var(--panel-2)' }} /></label>
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
