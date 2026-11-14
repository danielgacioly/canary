// The space for the on-board AI assistant. With no provider connected, answers come from
// the same tools and guard a model would use, so the whole path can be tested today.
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { AssistantAnswer, AssistantStatus, AssistantStatusValue, GuardReport, Observation, RecommendedAction, SourceMeta } from '../api/types'
import { Icon } from '../components/ui'
import { useSession } from '../state/session'

const MODE: Record<string, [string, string]> = {
  ai: ['AI answer', 's0'], grounded: ['Rule-based, from your data', 's0'], refused: ['Out of scope', 's1'],
  emergency: ['Emergency: use Guided Response', 's2'], unknown: ['Not in the data', 's1'],
  fallback: ['Model unavailable: rule-based answer', 's1'],
}
// Any mode the backend adds later still renders instead of crashing.
const modeOf = (m: string): [string, string] => MODE[m] ?? [m, 's1']
const STATUS: Record<AssistantStatusValue, [string, string]> = {
  supported: ['Supported by your data', 's0'], insufficient_evidence: ['Insufficient evidence', 's1'], out_of_scope: ['Out of scope', 's1'],
}
// kb:CARD-BRAIN@1#summary -> document, version, section (schema.md §6). `source_meta` adds title and excerpt when sent.
const KB_RE = /^kb:([A-Z0-9-]+)@(\d+)#([a-z0-9-]+)$/
const excerpt = (t: string, n = 180) => { const x = t.replace(/\s+/g, ' ').trim(); return x.length > n ? `${x.slice(0, n - 1).trimEnd()}…` : x }
const SUGGEST = ['How am I doing today?', 'Why is my sleep off?', 'What does space do to my bones?', 'Is my pulse normal?', 'Should I take melatonin?']

export default function AskCanary({ onClose }: { onClose: () => void }) {
  const { me, catalog, setEmergency, toast } = useSession()
  const navigate = useNavigate()
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
  // Title, version and excerpt for every kb: id the backend described, across the whole conversation.
  const meta: Record<string, SourceMeta> = Object.assign({}, ...items.map(a => a.source_meta ?? {}))
  const label = (id: string) => {
    const [kind, a, b] = id.split(':')
    if (kind === 'telemetry') return catalog?.indicators[b]?.name ?? b
    if (kind === 'card') return `${catalog?.systems[a]?.name ?? a} card`
    if (kind === 'protocol') return `protocol ${a}`
    if (kind === 'nasa') return `NASA ${a.toUpperCase()}`
    if (kind === 'kb') { const m = KB_RE.exec(id); return m ? `${m[1].toLowerCase()} v${m[2]}` : 'knowledge' }
    return kind
  }
  const hover = (id: string) => {
    const sm = meta[id]
    if (sm) return [`Approved knowledge · ${sm.title}${sm.version != null ? ` · version ${sm.version}` : ''}`, sm.text ? excerpt(sm.text) : ''].filter(Boolean).join('\n')
    const m = KB_RE.exec(id)
    if (m) return `Approved knowledge · ${m[1]} · version ${m[2]} · section ${m[3]}`
    if (id.startsWith('card:')) return `Body system card · ${id}`
    if (id.startsWith('protocol:')) return `Guided Response protocol · ${id}`
    return `From your data · ${id}`
  }
  const chips = (ids: string[]) => ids.map(s => <span key={s} className="cite" title={hover(s)}>{label(s)}</span>)
  const group = (title: string, rows: Observation[]) => !!rows.length && (
    <div className="ask-group"><span className="lbl">{title}</span>
      {rows.map((r, k) => <p key={k}>{r.statement} {chips(r.source_ids)}</p>)}</div>
  )
  // The model picks one action from an allow-list (schema.md §6); each id maps to a flow that already exists.
  const action = (ra: RecommendedAction) => {
    const [kind, arg] = ra.id.split(':')
    const btn = (onClick: () => void) => <button className="btn sm pri ask-action" onClick={onClick}>{ra.label}</button>
    if (kind === 'goal') return btn(() => { onClose(); navigate('/me/goals') })
    if (kind === 'protocol') return btn(() => { onClose(); setEmergency(arg || true) })
    if (kind === 'send_briefing' && me) return btn(async () => {
      try { await api.briefing(me); toast('Briefing draft prepared. Review it in the medical console before it is queued for Earth.') }
      catch { toast('Could not prepare the briefing right now.') }
    })
    const why = kind === 'contact_cmo' ? 'Talk to the crew medical officer in person or over crew comms. Messaging from here is not available yet.'
      : `This action (${arg ?? kind}) is not available here yet.`
    return <button className="btn sm ask-action" disabled title={why} aria-disabled="true">{ra.label}</button>
  }
  const guardNote = (g?: GuardReport) => g?.reason ? (
    <p className="ask-guard small">Guard: {g.reason}
      {!!g.dropped_claims.length && ` · ${g.dropped_claims.length} claim${g.dropped_claims.length > 1 ? 's' : ''} removed`}
      {!!g.rejected_numbers.length && ` · numbers not in the data: ${g.rejected_numbers.join(', ')}`}</p>
  ) : null
  return (
    <>
      <div className="scrim ask-scrim" style={{ background: 'rgba(2,3,7,.4)' }} onClick={onClose} />
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
                <div className="row wrap" style={{ gap: 10 }}>
                  <span className={`status ${modeOf(a.mode)[1]}`}><span className="dot" />{modeOf(a.mode)[0]}</span>
                  {a.status && STATUS[a.status] && <span className={`status ${STATUS[a.status][1]}`}>{STATUS[a.status][0]}</span>}
                </div>
                {a.observations || a.explanations ? (
                  <>
                    {/* Rule-based answers join the same claims shown below, so only the model's summary is repeated here. */}
                    {a.answer && (a.mode === 'ai' || !(a.observations?.length || a.explanations?.length)) && <p style={{ marginTop: 6 }}>{a.answer}</p>}
                    {group('Observed', a.observations ?? [])}
                    {group('Possible explanations', a.explanations ?? [])}
                  </>
                ) : a.claims.length ? a.claims.map((c, k) => (
                  <p key={k} style={{ marginTop: 6 }}>{c.text} {chips(c.source_ids)}</p>
                )) : <p style={{ marginTop: 6 }}>{a.answer}</p>}
                {!!a.limitations?.length && (
                  <div className="ask-group"><span className="lbl">Limitations</span>
                    <ul className="ask-limits small muted">{a.limitations.map((l, k) => <li key={k}>{l}</li>)}</ul></div>
                )}
                {a.recommended_action && a.mode !== 'emergency' && action(a.recommended_action)}
                {guardNote(a.guard)}
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
