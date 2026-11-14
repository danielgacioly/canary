// Guided Response: deterministic, step-by-step first response. No AI on this path.
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Emergency, Protocols } from '../api/types'
import { Icon } from '../components/ui'
import { useSession } from '../state/session'

const mmss = (s: number) => `${String(Math.floor(Math.max(0, s) / 60)).padStart(2, '0')}:${String(Math.floor(Math.max(0, s) % 60)).padStart(2, '0')}`

export default function GuidedResponse({ onClose }: { onClose: () => void }) {
  const { me, mission, catalog, bump, toast, prefs } = useSession()
  const [P, setP] = useState<Protocols | null>(null)
  const [em, setEm] = useState<Emergency | null>(null)
  const [pid, setPid] = useState<string | null>(null)
  const [i, setI] = useState(0)
  const [patient, setPatient] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())
  const [stepAt, setStepAt] = useState(Date.now())
  const [voice, setVoice] = useState(prefs.voice)
  const [done, setDone] = useState(false)

  useEffect(() => {
    api.protocols().then(setP)
    api.startEmergency(me).then(setEm)
    const t = setInterval(() => setNow(Date.now()), 250)
    return () => { clearInterval(t); try { speechSynthesis.cancel() } catch { /* no speech */ } }
  }, [me])

  const log = (text: string, extra: Record<string, unknown> = {}) => { if (em) api.emergencyEvent(em.id, { text, ...extra }).then(setEm) }
  const proto = pid && P ? P.protocols[pid] : null
  const step = proto?.steps[i]

  useEffect(() => {
    if (!voice || !step) return
    try {
      speechSynthesis.cancel()
      const u = new SpeechSynthesisUtterance([step.t, step.variant, step.q].filter(Boolean).join(' '))
      u.lang = 'en-US'
      speechSynthesis.speak(u)
    } catch { /* no speech */ }
  }, [voice, step])

  const pick = (id: string) => {
    setPid(id); setI(0); setStepAt(Date.now())
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
    if (em) await api.emergencyEvent(em.id, { close: true, outcome, patient: patient ?? undefined, protocol: pid ?? undefined })
    setDone(true); bump()
    toast(patient ? 'Follow-up goals added for the patient. Report queued for Earth.' : 'Report queued for Earth.')
  }

  const stepElapsed = (now - stepAt) / 1000
  return (
    <div className="er" role="dialog" aria-label="Guided Response">
      <div className="er-top">
        <i className="dot s2" style={{ background: 'var(--nasa-red)' }} />
        <div><span className="lbl">Guided Response · {mission?.place.name} · {mission?.place.gravity}</span><h2>{proto ? proto.name : 'What is happening?'}</h2></div>
        <div className="right row" style={{ gap: 22 }}>
          <span className="small muted">{mission?.place.reply === 'Live' ? 'Earth sees this live' : `Earth sees this ${mission?.place.reply} later`}</span>
          <button className={`btn er-btn ${voice ? 'pri' : ''}`} onClick={() => setVoice(v => !v)}>Voice {voice ? 'on' : 'off'}</button>
          <button className="btn er-btn" onClick={onClose}><Icon name="close" size={18} />Close</button>
        </div>
      </div>

      <div className="er-body">
        <div className="col" style={{ gap: 18 }}>
          {!P && <span className="lbl">Loading protocols…</span>}
          {P && !proto && !done && (
            <>
              <p className="er-lead">Crew alerted. Pick what you see. If unsure, choose “I don’t know” and answer yes or no.</p>
              <div className="proto-grid">
                {P.order.map(id => (
                  <button key={id} className="proto" onClick={() => pick(id)}>
                    <b>{P.protocols[id].name}</b>
                    <span className="muted">{P.protocols[id].sign}</span>
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
                  <p className="er-lead">Who was the patient?</p>
                  <div className="er-choices">{catalog?.crew.map(c => <button key={c.id} className={`btn er-btn big ${patient === c.id ? 'pri' : ''}`} onClick={() => { setPatient(c.id); log(`Patient: ${c.name}`, { patient: c.id }) }}>{c.name}</button>)}</div>
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
          <p className="small dim">Protocols are illustrative and not clinically reviewed. They are data the medical team can replace.</p>
        </aside>
      </div>
    </div>
  )
}
