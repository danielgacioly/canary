// The space for the on-board AI assistant. With no provider connected, answers come from
// the same tools and guard a model would use, so the whole path can be tested today.
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { AssistantAnswer, AssistantStatus } from '../api/types'
import { Icon } from '../components/ui'
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
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.assistantStatus().then(setStatus)
    if (me) api.askHistory(me).then(setItems)
  }, [me])
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }) }, [items])

  const ask = async (text: string) => {
    if (!me || !text.trim()) return
    setBusy(true); setQ('')
    try { const r = await api.ask(me, text); setItems(x => [...x, { ...r, question: text }]) } finally { setBusy(false) }
  }
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
      <div className="scrim" style={{ background: 'rgba(2,3,7,.4)' }} onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Ask Canary">
        <div className="row" style={{ padding: '18px 18px 12px', borderBottom: '1px solid var(--line)' }}>
          <div><h2>Ask Canary</h2><div className="small muted">Explains your data. Never diagnoses.</div></div>
          <button className="btn sm ghost right" onClick={onClose}><Icon name="close" size={15} /></button>
        </div>
        <div style={{ padding: '12px 18px' }}>
          <div className="slot">
            <div className="row"><span className="lbl">AI slot</span>
              <span className="tag right">{status ? (status.configured ? `provider: ${status.provider}` : 'no model connected') : '…'}</span></div>
            <p className="small muted" style={{ marginTop: 6 }}>
              It explains, it does not diagnose. Every sentence cites where it came from. Without a model, answers are built by rules from the same data.
            </p>
          </div>
        </div>
        <div className="chat">
          {!me && <p className="muted small"><b style={{ color: 'var(--ink)' }}>Enter your space first.</b> Canary answers only about your own data, and only once you have entered. Tap your name under My health.</p>}
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
          {busy && <span className="lbl">Checking your data…</span>}
          <div ref={end} />
        </div>
        <div style={{ padding: 14, borderTop: '1px solid var(--line)' }}>
          <div className="row wrap" style={{ gap: 6, marginBottom: 10 }}>{SUGGEST.map(s => <button key={s} className="btn sm" onClick={() => ask(s)}>{s}</button>)}</div>
          <form className="row" onSubmit={e => { e.preventDefault(); ask(q) }}>
            <input className="grow" value={q} onChange={e => setQ(e.target.value)} placeholder="Ask about your health data…" maxLength={500}
              style={{ padding: '10px 12px', borderRadius: 8, border: '1px solid var(--line-2)', background: 'var(--bg)' }} />
            <button className="btn pri" disabled={busy || !q.trim()} aria-label="Send"><Icon name="send" size={15} /></button>
          </form>
        </div>
      </aside>
    </>
  )
}
