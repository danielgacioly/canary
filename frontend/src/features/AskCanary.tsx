// The space for the on-board AI assistant. With no provider connected, answers come from
// the same tools and guard a model would use, so the whole path can be tested today.
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { AssistantAnswer, AssistantStatus } from '../api/types'
import { ActionError, Field, FormError } from '../components/Field'
import { Icon } from '../components/ui'
import { useAction } from '../lib/useAction'
import { useForm } from '../lib/useForm'
import * as v from '../lib/validate'
import { useSession } from '../state/session'

const MODE: Record<string, [string, string]> = {
  ai: ['AI answer', 's0'], grounded: ['Rule-based, from your data', 's0'], refused: ['Out of scope', 's1'],
  emergency: ['Emergency: use Guided Response', 's2'], unknown: ['Not in the data', 's1'],
}
const SUGGEST = ['How am I doing today?', 'Why is my sleep off?', 'What does space do to my bones?', 'Is my pulse normal?', 'Should I take melatonin?']

export default function AskCanary({ onClose }: { onClose: () => void }) {
  const { me, catalog, setEmergency } = useSession()
  const [status, setStatus] = useState<AssistantStatus | null>(null)
  const [items, setItems] = useState<AssistantAnswer[]>([])
  const [busy, setBusy] = useState(false)
  const [loadErr, setLoadErr] = useState<string | null>(null)
  const sug = useAction()
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.assistantStatus().then(setStatus).catch(() => setLoadErr('Could not reach the assistant. Questions will not work until the connection is back.'))
    if (me) api.askHistory(me).then(setItems).catch(() => setLoadErr('Could not load your earlier questions.'))
  }, [me])
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }) }, [items])

  /** Sends one question. Throws when it is refused or the server is down: the caller shows the message. */
  const ask = async (text: string) => {
    if (!me) throw new Error('Enter your space first: Canary answers only about your own data.')
    setBusy(true)
    try { const r = await api.ask(me, text); setItems(x => [...x, { ...r, question: text }]) } finally { setBusy(false) }
  }
  const form = useForm({
    initial: { q: '' },
    validate: f => ({ q: v.length('Question', { max: 500 })(f.q) }),
    submit: async f => { await ask(f.q.trim()); form.reset({ q: '' }) },
  })
  const label = (id: string) => {
    const [kind, a, b] = id.split(':')
    if (kind === 'telemetry') return catalog?.indicators[b]?.name ?? b
    if (kind === 'card') return `${catalog?.systems[a]?.name ?? a} card`
    if (kind === 'protocol') return `protocol ${a}`
    if (kind === 'nasa') return `NASA ${a.toUpperCase()}`
    return kind
  }
  return (
    <>
      <div className="scrim soft" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Ask Canary">
        <div className="row drawer-head">
          <div><h2>Ask Canary</h2><div className="small muted">Explains your data. Never diagnoses.</div></div>
          <button className="btn sm ghost right" onClick={onClose}><Icon name="close" size={15} /></button>
        </div>
        <div className="drawer-body">
          <div className="slot">
            <div className="row"><span className="lbl">AI slot</span>
              <span className="tag right">{status ? (status.configured ? `provider: ${status.provider}` : 'no model connected') : '…'}</span></div>
            <p className="small muted" style={{ marginTop: 6 }}>
              It explains, it does not diagnose. Every sentence cites where it came from. Without a model, answers are built by rules from the same data.
            </p>
          </div>
        </div>
        <div className="chat">
          {!me && <p className="muted small"><b className="ink">Enter your space first.</b> Canary answers only about your own data, and only once you have entered. Tap your name under My health.</p>}
          {me && !items.length && <p className="muted small">Ask about your numbers, a body system or what to do today. Emergencies go to the red button.</p>}
          {items.map(a => (
            <div key={a.id} className="col" style={{ gap: 8 }}>
              <div className="bubble me">{a.question}</div>
              <div className="bubble bot">
                <span className={`status ${MODE[a.mode][1]}`}><span className="dot" />{MODE[a.mode][0]}</span>
                {a.claims.length ? a.claims.map((c, k) => (
                  <p key={k} style={{ marginTop: 6 }}>{c.text} {c.source_ids.map(s => <span key={s} className="cite" title={s}>{label(s)}</span>)}</p>
                )) : <p style={{ marginTop: 6 }}>{a.answer}</p>}
                {a.mode === 'emergency' && <button className="btn sm" style={{ marginTop: 10 }} onClick={() => { onClose(); setEmergency(true) }}>Open Guided Response</button>}
                {!!a.tools_used.length && <p className="small dim" style={{ marginTop: 8 }}>Tools: {a.tools_used.map(t => t.tool).join(', ')}</p>}
              </div>
            </div>
          ))}
          {loadErr && <p className="small err" role="alert">{loadErr}</p>}
          {busy && <span className="lbl">Checking your data…</span>}
          <div ref={end} />
        </div>
        <div className="drawer-foot">
          <div className="row wrap drawer-suggest">{SUGGEST.map(s => <button key={s} className="btn sm" disabled={busy} onClick={() => sug.run(() => ask(s))}>{s}</button>)}</div>
          <ActionError error={sug.error} />
          <form noValidate onSubmit={form.submit}>
            <div className="row ask-row">
              <div className="grow"><Field form={form} name="q" label="Your question" hideLabel placeholder="Ask about your health data…" hint="Up to 500 characters" maxLength={500} autoComplete="off" /></div>
              <button className="btn pri" disabled={busy || form.busy} aria-label="Send"><Icon name="send" size={15} /></button>
            </div>
            <FormError form={form} />
          </form>
        </div>
      </aside>
    </>
  )
}
