// Guided Response: deterministic, step-by-step first response. No AI on this path.
import { useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Emergency, ProtocolMatch, Protocols } from '../api/types'
import { Icon } from '../components/ui'
import { screenSpeech, speakWithChirp, useEnglishVoice } from '../lib/voice'
import { useSession } from '../state/session'

const STABLE_Q = 'Is the patient stable?'
const CHIPS = ['Not breathing', 'Seizure', 'Choking', 'Bleeding', 'Chest pain', 'Fainted', 'Allergic reaction', 'Eye injury', 'Panic or crisis', 'Radiation alarm']

/** The person describes what they see; Canary ranks the protocols by the words. Nothing starts by itself. */
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
    <div className="er-screen">
      <h3 className="er-ask">Say what you see.</h3>
      <textarea className="er-describe" rows={2} autoFocus value={text} maxLength={500} aria-label="What do you see?" placeholder="He is shaking and not responding"
        onChange={e => { setText(e.target.value); setRes(null) }}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); find(text) } }} />
      <div className="er-chips">{CHIPS.map(c => <button key={c} className="er-chip" onClick={() => { setText(c); find(c) }}>{c}</button>)}</div>
      {!res && <button className="er-main" disabled={!text.trim() || busy} onClick={() => find(text)}>{busy ? 'Looking…' : 'Find the protocol'}<Icon name="chev" size={26} /></button>}
      {res && best && (
        <div className="er-result">
          <h3 className="er-match-name">{name(best.id)}</h3>
          <button className="er-main" onClick={() => onStart(best.id, res.q)}>Start<Icon name="chev" size={26} /></button>
          {rest.length > 0 && <div className="er-alts">{rest.map(m => (
            <button key={m.id} className="er-alt" onClick={() => onStart(m.id, res.q)}>{name(m.id)}<Icon name="chev" size={18} /></button>
          ))}</div>}
        </div>
      )}
      {res && !best && (
        <div className="er-result">
          <h3 className="er-match-name">No protocol matches.</h3>
          <button className="er-main" onClick={() => onStart(res.r.fallback?.id ?? 'cpr', res.q)}>Start basic life support<Icon name="chev" size={26} /></button>
        </div>
      )}
      <button className="er-link" onClick={onBack}>Choose from the list</button>
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
  const { me, catalog, bump, toast, prefs, emergencyPid } = useSession()
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
  const closing = useRef(false)  // set by Close: a record that arrives after it is cancelled, not shown

  useEffect(() => {
    api.protocols().then(setP).catch(e => toast(`Could not load the protocols: ${errorText(e)}`))
    api.startEmergency(me, token.current)
      .then(e => { if (closing.current) return api.emergencyEvent(e.id, { cancel: true }).then(() => bump()); setEm(e) })
      .catch(e => toast(`Could not open the emergency record: ${errorText(e)}`))
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

  const eng = useEnglishVoice()
  // What the screen shows is what is read, once per screen. With no English voice it stays silent: English text read by
  // a foreign voice is worse than none.
  const speech = !P ? null
    : done ? { key: 'done', text: screenSpeech(['Closed and reported.']) }
    : patient === null ? { key: 'patient', text: screenSpeech(['Who is the patient?']) }
    : proto && step ? { key: `${pid}-${i}`, text: screenSpeech([step.t, step.variant, step.q, step.end ? STABLE_Q : null]) }
    : describing ? { key: 'describe', text: screenSpeech(['Say what you see.']) }
    : { key: 'choose', text: screenSpeech(['What is happening?', 'Choose what you see.']) }
  const speechKey = speech ? `${speech.key}|${speech.text}` : ''
  useEffect(() => {
    if (!voice || !speech?.text || !eng.voice) return
    return speakWithChirp(speech.text, eng.voice)
  }, [voice, speechKey, eng.voice])  // eslint-disable-line react-hooks/exhaustive-deps

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
  // Close before the end cancels the emergency, so the cabin alarm stops. Never in an effect cleanup: React may run those twice.
  const cancelAndClose = async () => {
    if (done || closing.current) { onClose(); return }
    closing.current = true
    await chain.current  // the steps already logged stay in the record
    const id = emRef.current?.id
    if (id !== undefined) {
      try { await api.emergencyEvent(id, { cancel: true }); toast('Emergency cancelled.') }
      catch (e) { toast(`The emergency was not cancelled: ${errorText(e)}. Cancel it from the red bar.`) }
    }
    bump()
    onClose()
  }

  const stepElapsed = (now - stepAt) / 1000
  const noVoice = eng.checked && !eng.voice
  return (
    <div className="er" role="dialog" aria-label="Emergency">
      <div className="er-top">
        <i className="er-dot" aria-hidden="true" />
        <h2 className="er-title">{proto ? proto.name : 'Emergency'}</h2>
        <div className="er-tools">
          <button className={`er-tool ${voice && !noVoice ? 'on' : ''}`} aria-pressed={voice && !noVoice} disabled={noVoice} onClick={() => setVoice(v => !v)}
            title={noVoice ? 'No English voice on this device' : eng.voice ? `${eng.voice.name} (${eng.voice.lang})` : undefined} data-voice={eng.voice?.name ?? ''}>
            <Icon name={voice && !noVoice ? 'sound' : 'mute'} size={22} /><span className="er-long">{noVoice ? 'No voice' : voice ? 'Voice on' : 'Turn voice on'}</span><span className="er-short">Voice</span>
          </button>
          <button className="er-tool" onClick={cancelAndClose} aria-label={done ? 'Close' : 'Cancel emergency'}><Icon name="close" size={22} />{done ? 'Close' : 'Cancel'}</button>
        </div>
      </div>

      <div className="er-body">
        {!P && <p className="er-ask">Loading…</p>}
        {P && patient === null && !done && (
          <div className="er-screen">
            <h3 className="er-ask">Who is the patient?</h3>
            <div className="er-tiles">
              {catalog?.crew.map(c => <button key={c.id} className="er-tile" onClick={() => { setPatient(c.id); log(`Patient: ${c.name}`, { patient: c.id }) }}><b>{c.name}</b></button>)}
              <button className="er-tile" onClick={() => { setPatient(''); log('Patient: not a crew member') }}><b>Someone else</b></button>
            </div>
          </div>
        )}
        {P && patient !== null && !proto && !done && describing && <Describe P={P} onStart={(id, text) => { log(`Described: ${text}`); pick(id) }} onBack={() => setDescribing(false)} />}
        {P && patient !== null && !proto && !done && !describing && (
          <div className="er-screen">
            <h3 className="er-ask">What is happening?</h3>
            <div className="er-tiles">
              {P.order.map(id => (
                <button key={id} className={`er-tile ${id === 'triage' ? 'unsure' : ''}`} onClick={() => pick(id)}>
                  <b>{P.protocols[id].name}</b>
                  <span>{id === 'triage' ? 'Say what you see' : P.protocols[id].sign}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {proto && step && !done && (
          <div className="er-screen" key={`${pid}-${i}`}>
            <div className="er-progress" role="progressbar" aria-label="Step" aria-valuemin={1} aria-valuemax={proto.steps.length} aria-valuenow={i + 1}>
              <div className="er-bar"><i style={{ width: `${(100 * (i + 1)) / proto.steps.length}%` }} /></div>
              <span>{i + 1}/{proto.steps.length}</span>
            </div>
            {step.t && <p className="er-do">{step.t}</p>}
            {step.variant && <p className="er-here">{step.variant}</p>}
            {i === 0 && proto.kit.length > 0 && <p className="er-kit"><b>Bring:</b> {proto.kit.join(', ')}</p>}
            {step.metro ? <div><div className="metro" /><p className="er-sub">Push on every pulse: 110 per minute</p></div> : null}
            {step.breath ? <div><div className="breath" /><p className="er-sub">In as it grows, out as it shrinks</p></div> : null}
            {step.timer ? <b className="timer">{mmss(step.timer - stepElapsed)}</b> : null}
            {step.q && <p className="er-q">{step.q}</p>}
            {step.q ? (
              <div className="yesno"><button className="y" onClick={() => answer(true)}>YES</button><button className="n" onClick={() => answer(false)}>NO</button></div>
            ) : step.end ? (
              <>
                <p className="er-q">{STABLE_Q}</p>
                <div className="er-outcomes">
                  <button className="er-main ok" onClick={() => finish('stable')}>Stable: close and report</button>
                  <button className="er-main bad" onClick={() => finish('needs evacuation review')}>Not stable: escalate</button>
                </div>
              </>
            ) : (
              <button className="er-main" onClick={() => { log(`Done: step ${i + 1}`); go(undefined) }}>Done, next<Icon name="chev" size={26} /></button>
            )}
            <button className="er-link" onClick={() => setPid(null)}>Wrong protocol? Choose again</button>
          </div>
        )}
        {done && (
          <div className="er-screen">
            <h3 className="er-ask">Closed and reported.</h3>
            {proto && proto.after.length > 0 && <ul className="er-after">{proto.after.map(a => <li key={a}>{a}</li>)}</ul>}
            <button className="er-main" onClick={onClose}>Back to Canary</button>
          </div>
        )}
      </div>
    </div>
  )
}
