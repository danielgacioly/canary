// Guided Response: deterministic, step-by-step first response. No AI on this path.
import { useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Emergency, ProtocolMatch, Protocols } from '../api/types'
import { Icon } from '../components/ui'
import { speakWithChirp, stepSpeech, useEnglishVoice } from '../lib/voice'
import { useSession } from '../state/session'

const CHIPS = ['Not breathing', 'Seizure', 'Choking', 'Bleeding', 'Chest pain', 'Fainted', 'Allergic reaction', 'Eye injury', 'Panic or crisis', 'Radiation alarm']

/** The person describes what they see; Canary ranks the protocols by the words (rules, shown). Nothing starts by itself. */
function Describe({ P, onStart, onBack }: { P: Protocols; onStart: (id: string, text: string) => void; onBack: () => void }) {
  const { toast } = useSession()
  const [text, setText] = useState('')
  const [res, setRes] = useState<{ q: string; r: ProtocolMatch } | null>(null)
  const [busy, setBusy] = useState(false)
  const find = async (q: string) => {
    const t = q.trim()
    if (!t || busy) return
    setBusy(true)
    try { setRes({ q: t, r: await api.matchProtocol(t) }) } catch (e) { toast(`Could not match that: ${errorText(e)}. Pick from the list instead.`) }
    setBusy(false)
  }
  const best = res?.r.matches[0], rest = res?.r.matches.slice(1) ?? []
  const name = (id: string) => P.protocols[id]?.name ?? id
  return (
    <div className="col" style={{ gap: 18 }}>
      <p className="er-lead">Say what you see, in your own words.</p>
      <textarea className="er-describe" rows={3} autoFocus value={text} maxLength={500} aria-label="What do you see?" placeholder="For example: he is shaking and not responding"
        onChange={e => { setText(e.target.value); setRes(null) }}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); find(text) } }} />
      <div className="er-choices">{CHIPS.map(c => <button key={c} className="btn er-btn" onClick={() => { setText(c); find(c) }}>{c}</button>)}</div>
      <div className="row wrap">
        <button className="btn pri er-btn big" disabled={!text.trim() || busy} onClick={() => find(text)}>{busy ? 'Looking…' : 'Find the protocol'}</button>
        <button className="btn ghost er-btn" onClick={onBack}>Choose from the list</button>
      </div>
      {res && best && (
        <div className="col detail" style={{ gap: 14 }}>
          <div className="er-match">
            <span className="lbl">Closest match</span>
            <h3 className="er-big">{name(best.id)}</h3>
            <p className="muted">{best.sign}. You said: {best.matched.length ? best.matched.map(w => `“${w}”`).join(', ') : 'nothing that matches by word'}.</p>
            <button className="btn pri er-next" onClick={() => onStart(best.id, res.q)}>Start this protocol<Icon name="chev" size={24} /></button>
          </div>
          {rest.length > 0 && (
            <div className="col" style={{ gap: 8 }}>
              <span className="lbl">It could also be</span>
              {rest.map(m => (
                <div key={m.id} className="row er-alt"><span className="grow"><b>{name(m.id)}</b> <span className="muted">{m.matched.map(w => `“${w}”`).join(', ')}</span></span>
                  <button className="btn er-btn" onClick={() => onStart(m.id, res.q)}>Start</button></div>
              ))}
            </div>
          )}
        </div>
      )}
      {res && !best && (
        <div className="col detail" style={{ gap: 12 }}>
          <p className="er-big">No protocol matches.</p>
          <p className="muted">Nothing in what you wrote fits a protocol here. If the person is not responding or not breathing, start basic life support. Otherwise choose from the list.</p>
          <button className="btn pri er-next" onClick={() => onStart(res.r.fallback?.id ?? 'cpr', res.q)}>No protocol matches — start basic life support<Icon name="chev" size={24} /></button>
        </div>
      )}
    </div>
  )
}

const mmss = (s: number) => `${String(Math.floor(Math.max(0, s) / 60)).padStart(2, '0')}:${String(Math.floor(Math.max(0, s) % 60)).padStart(2, '0')}`

// One id per opening: a retry of the same opening (for example React running an effect twice) gets the same emergency back.
const newToken = () => globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`

/** `initialProtocol` opens that protocol directly; an unknown id falls back to the chooser. Without the prop, the protocol
 * id from the session (`emergencyPid`, set by a protocol's page or setEmergency(id)) is used. The patient is asked first, so
 * the protocol and the report are about that person. */
export default function GuidedResponse({ onClose, initialProtocol }: { onClose: () => void; initialProtocol?: string }) {
  const { me, mission, catalog, bump, toast, prefs, emergencyPid } = useSession()
  const initial = initialProtocol ?? emergencyPid ?? undefined
  const [P, setP] = useState<Protocols | null>(null)
  const [em, setEm] = useState<Emergency | null>(null)
  const [pid, setPid] = useState<string | null>(null)
  const [i, setI] = useState(0)
  const [patient, setPatient] = useState<string | null>(null)  // chosen first: a crew id, or '' for someone not on the crew
  const [now, setNow] = useState(Date.now())
  const [stepAt, setStepAt] = useState(Date.now())
  const [voice, setVoice] = useState(prefs.voice)
  const [done, setDone] = useState(false)
  const [describing, setDescribing] = useState(false)  // "I don't know": the person says what they see, Canary suggests a protocol
  const token = useRef(newToken())

  useEffect(() => {
    api.protocols().then(setP).catch(e => toast(`Could not load the protocols: ${errorText(e)}`))
    api.startEmergency(me, token.current).then(setEm).catch(e => toast(`Could not open the emergency record: ${errorText(e)}`))
    const t = setInterval(() => setNow(Date.now()), 250)
    return () => { clearInterval(t); try { speechSynthesis.cancel() } catch { /* no speech */ } }
  }, [me])

  // Log calls keep their order. One made before the emergency id exists waits in `pending` and is sent once it does.
  const emRef = useRef<Emergency | null>(null)
  const pending = useRef<{ text?: string; protocol?: string; patient?: string }[]>([])
  const chain = useRef<Promise<unknown>>(Promise.resolve())
  const send = (p: { text?: string; protocol?: string; patient?: string }) => {
    chain.current = chain.current.then(() => api.emergencyEvent(emRef.current!.id, p)).then(setEm).catch(e => toast(`The log did not save that step: ${errorText(e)}`))
  }
  useEffect(() => {
    emRef.current = em
    if (em && pending.current.length) { const q = pending.current; pending.current = []; q.forEach(send) }
  }, [em])  // eslint-disable-line react-hooks/exhaustive-deps
  const log = (text: string, extra: { protocol?: string; patient?: string } = {}) => {
    const p = { text, ...extra }
    if (emRef.current) send(p); else pending.current.push(p)
  }

  // Open the requested protocol once the list is loaded; log it once the emergency record exists.
  const opened = useRef(false)
  const unlogged = useRef<string | null>(null)
  useEffect(() => {
    if (!P || opened.current) return
    opened.current = true
    if (initial && P.protocols[initial]) { setPid(initial); setI(0); setStepAt(Date.now()); unlogged.current = initial }
  }, [P, initial])
  useEffect(() => {
    const id = unlogged.current
    if (!em || !P || !id) return
    unlogged.current = null
    log(`Protocol: ${P.protocols[id].name}`, { protocol: id })
  }, [em, P, pid])  // eslint-disable-line react-hooks/exhaustive-deps
  const proto = pid && P ? P.protocols[pid] : null
  const step = proto?.steps[i]
  const patientName = patient ? catalog?.crew.find(c => c.id === patient)?.name ?? patient : patient === '' ? 'Not a crew member' : null

  const eng = useEnglishVoice()
  // With no English voice the step stays silent: an English text read by a foreign voice is worse than none.
  useEffect(() => {
    if (!voice || !step || !proto || !eng.voice) return
    return speakWithChirp(stepSpeech(i, proto.steps.length, [step.t, step.variant, step.q]), eng.voice)
  }, [voice, step, proto, i, eng.voice])

  const pick = (id: string) => {
    if (id === 'triage') { setDescribing(true); return }  // the yes/no guessing is replaced by a description
    setDescribing(false); setPid(id); setI(0); setStepAt(Date.now())
    log(`Protocol: ${P?.protocols[id].name}`, { protocol: id })
  }
  const go = (to: number | string | undefined) => {
    if (to === undefined) { setI(x => x + 1); setStepAt(Date.now()); return }
    if (typeof to === 'string') { log(`Switched to ${P?.protocols[to].name}`, { protocol: to }); setPid(to); setI(to === 'cpr' ? 1 : 0) } else setI(to)
    setStepAt(Date.now())
  }
  const answer = (yes: boolean) => {
    if (!step) return
    log(`${step.q} ${yes ? 'Yes' : 'No'}`)
    go(yes ? step.yes : step.no)
  }
  const finish = async (outcome: string) => {
    await chain.current  // the log is complete before the report closes
    try {
      if (em) await api.emergencyEvent(em.id, { close: true, outcome, patient: patient || undefined, protocol: pid ?? undefined })
    } catch (e) { toast(`The report was not closed: ${errorText(e)}. Press the button again.`); return }
    setDone(true); bump()
    toast(patient ? 'Follow-up goals added for the patient. Report queued for Earth.' : 'Report queued for Earth.')
  }

  const illustrative = !!P && P.order.some(id => P.protocols[id]?.status === 'illustrative')
  const stepElapsed = (now - stepAt) / 1000
  return (
    <div className="er" role="dialog" aria-label="Guided Response">
      <div className="er-top">
        <i className="dot s2" style={{ background: 'var(--nasa-red)' }} />
        <div><span className="lbl">Guided Response · {mission?.place.name} · {mission?.place.gravity}</span><h2>{proto ? proto.name : 'What is happening?'}</h2></div>
        <div className="right row" style={{ gap: 22 }}>
          <span className="small muted">{mission?.place.reply === 'Live' ? 'Earth sees this live' : `Earth sees this ${mission?.place.reply} later`}</span>
          <div className="er-voice">
            <button className={`btn er-btn ${voice ? 'pri' : ''}`} onClick={() => setVoice(v => !v)} title={eng.voice ? `${eng.voice.name} (${eng.voice.lang})` : undefined} data-voice={eng.voice?.name ?? ''}>Voice {voice ? 'on' : 'off'}</button>
            {eng.checked && !eng.voice && <span className="small dim">No English voice on this device</span>}
          </div>
          <button className="btn er-btn" onClick={onClose}><Icon name="close" size={18} />Close</button>
        </div>
      </div>

      <div className="er-body">
        <div className="col" style={{ gap: 18 }}>
          {!P && <span className="lbl">Loading protocols…</span>}
          {P && patient === null && !done && (
            <div className="col" style={{ gap: 18 }}>
              <p className="er-lead">Who is the patient?</p>
              <div className="er-choices">
                {catalog?.crew.map(c => <button key={c.id} className="btn er-btn big" onClick={() => { setPatient(c.id); log(`Patient: ${c.name}`, { patient: c.id }) }}>{c.name}</button>)}
                <button className="btn er-btn big" onClick={() => { setPatient(''); log('Patient: not a crew member') }}>Someone else</button>
              </div>
            </div>
          )}
          {P && patient !== null && !proto && !done && describing && <Describe P={P} onStart={(id, text) => { log(`Described: ${text}`); pick(id) }} onBack={() => setDescribing(false)} />}
          {P && patient !== null && !proto && !done && !describing && (
            <>
              <p className="er-lead">Patient: <b>{patientName}</b>. Crew alerted. Pick what you see. If unsure, choose “I don’t know” and describe it.</p>
              <div className="proto-grid">
                {P.order.map(id => (
                  <button key={id} className="proto" onClick={() => pick(id)}>
                    <b>{P.protocols[id].name}</b>
                    <span className="muted">{id === 'triage' ? 'Say what you see' : P.protocols[id].sign}</span>
                  </button>
                ))}
              </div>
            </>
          )}
          {proto && step && !done && (
            <div className="col detail" key={`${pid}-${i}`} style={{ gap: 18 }}>
              <span className="er-step">Step {i + 1} of {proto.steps.length}</span>
              {step.t && <p className="er-big">{step.t}</p>}
              {step.variant && <div className="er-variant"><span className="lbl">Here, at {mission?.place.name}</span><p style={{ marginTop: 6, fontSize: 20, lineHeight: 1.45 }}>{step.variant}</p></div>}
              {step.metro ? <div><div className="metro" /><p className="small muted" style={{ textAlign: 'center' }}>Push on every pulse: 110 per minute</p></div> : null}
              {step.breath ? <div><div className="breath" /><p className="small muted" style={{ textAlign: 'center' }}>In as it grows, out as it shrinks</p></div> : null}
              {step.timer ? <div className="row"><span className="lbl">Timer</span><b className="timer">{mmss(step.timer - stepElapsed)}</b></div> : null}
              {step.q && <p className="er-big" style={{ color: 'var(--watch)' }}>{step.q}</p>}
              {step.q ? (
                <div className="yesno"><button className="y" onClick={() => answer(true)}>YES</button><button className="n" onClick={() => answer(false)}>NO</button></div>
              ) : step.end ? (
                <div className="col">
                  <div className="er-choices" style={{ marginTop: 8 }}>
                    <button className="btn pri er-btn big" onClick={() => finish('stable')}>Patient stable: close and report</button>
                    <button className="btn er-btn big" onClick={() => finish('needs evacuation review')}>Not stable: escalate</button>
                  </div>
                </div>
              ) : (
                <button className="btn pri er-next" onClick={() => { log(`Done: step ${i + 1}`); go(undefined) }}>Done, next step<Icon name="chev" size={24} /></button>
              )}
              <button className="btn ghost er-btn" style={{ alignSelf: 'flex-start' }} onClick={() => setPid(null)}>Wrong protocol? Choose again</button>
            </div>
          )}
          {done && (
            <div className="card detail">
              <h2>Closed and reported.</h2>
              <p className="muted" style={{ marginTop: 8 }}>The log is attached to the report. Follow-up care appears as goals for the patient over the next 3 days.</p>
              {proto && <ul className="steps">{proto.after.map(a => <li key={a}>{a}</li>)}</ul>}
              <button className="btn pri er-next" style={{ marginTop: 16 }} onClick={onClose}>Back to Canary</button>
            </div>
          )}
        </div>

        <aside className="col">
          {proto && <div className="card pad-sm"><span className="lbl">Bring</span><ul className="steps">{proto.kit.length ? proto.kit.map(k => <li key={k}>{k}</li>) : <li>Medical kit</li>}</ul></div>}
          <details className="er-log">
            <summary>Log · {(em?.log ?? []).length} {(em?.log ?? []).length === 1 ? 'entry' : 'entries'}, sent with the report</summary>
            <div className="col" style={{ gap: 4, marginTop: 8, maxHeight: 180, overflow: 'auto' }}>
              {(em?.log ?? []).slice().reverse().map(([t, x], k) => <div key={k} className="row small" style={{ alignItems: 'baseline' }}><span className="num dim">{mmss(t)}</span><span>{x}</span></div>)}
            </div>
          </details>
          {illustrative && (
            <span className="chip" data-testid="protocol-status" title={proto?.version ? `Protocol version ${proto.version}` : undefined}>
              Illustrative — not clinically reviewed{proto?.version ? ` · v${proto.version}` : ''}
            </span>
          )}
          <p className="small dim">They are data the medical team can replace.</p>
        </aside>
      </div>
    </div>
  )
}
