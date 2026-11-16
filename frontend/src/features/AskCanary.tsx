// The assistant drawer. Without a model connected, answers come from the same tools and guard, built by rules.
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { AssistantAnswer, AssistantStatus, AssistantStatusValue, GuardReport, Observation, RecommendedAction, SourceMeta } from '../api/types'
import { ActionError, Field, FormError } from '../components/Field'
import { Icon } from '../components/ui'
import { modelLine } from '../lib/assistant'
import { useAction } from '../lib/useAction'
import { useForm } from '../lib/useForm'
import * as v from '../lib/validate'
import { useSession } from '../state/session'

// Plain sentences for the astronaut. The raw rule ids and guard exits stay in the medical audit (schema.md §6).
const RULE_TEXT: [RegExp, string][] = [
  [/^G-(DOSE|OUT-DOSE)/, "I can't advise on medication or doses."],
  [/^G-(DIAG|OUT-DIAG)/, "I can't diagnose. I can show your numbers against your own normal."],
  [/^G-INJECT/, "I can't change how I work. I stay within Canary's safety rules."],
  [/^G-EMERG/, 'This sounds like an emergency. Use Guided Response.'],
  [/^G-NUM/, 'Part of the answer used numbers that are not in your data, so it was removed.'],
  [/^G-SRC/, 'Some statements had no valid source, so they were removed.'],
  [/^G-PRIV/, "Parts about other people were removed. I only talk about your data."],
  [/^G-WELL/, 'Wellbeing answers are a screening, never a diagnosis.'],
  [/^G-ACT/, 'The suggested next step was not available, so none is shown.'],
  [/^G-STATUS/, 'There is not enough data to call this supported.'],
  [/^G-OUT-SAFE/, "I can't say that something is safe."],
  [/^G-SCHEMA/, 'The answer could not be read, so it comes from your data.'],
  [/^loop:timeout|^api:timeout|^model:max_tokens/, 'The assistant took too long; this answer comes from your data.'],
  [/^api:rate_limit/, 'The AI service is busy; this answer comes from your data.'],
  [/^api:|^model:refusal|^model:bad_output/, 'The AI service could not give an answer; this answer comes from your data.'],
  [/^loop:/, 'The assistant needed too many steps; this answer comes from your data.'],
]
/** One plain sentence per guard rule or exit the answer fired (crew view). Unknown ids get no sentence. */
export function plainGuard(ids: string[]): string[] {
  const out: string[] = []
  for (const id of ids) {
    const hit = RULE_TEXT.find(([re]) => re.test(id))
    if (hit && !out.includes(hit[1])) out.push(hit[1])
  }
  return out
}

const MODE: Record<string, [string, string]> = {
  ai: ['AI answer', 's0'], grounded: ['From your data', 's0'], refused: ['Out of scope', 's1'],
  emergency: ['Emergency: use Guided Response', 's2'], unknown: ['Not in your data', 's1'],
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
// Names for the source chips (the backend ids carry the codes, not the words). Same names as the backend.
const HAZARD_NAMES: Record<string, string> = { R: 'Radiation', I: 'Isolation & confinement', D: 'Distance from Earth', G: 'Gravity', E: 'Hostile, closed environment' }
const RISK_NAMES: Record<string, string> = {
  fatigue: 'Behavioural health and performance', radiation: 'Radiation', sans: 'Vision and eye pressure (SANS)', nutrition: 'Food and nutrition',
  renal: 'Kidneys and hydration', immune: 'Blood and immunity', cardio: 'Heart and circulation', bone_muscle: 'Bones and muscles',
}
const SUGGEST = ['How am I doing today?', 'Why is my sleep off?', 'What does space do to my bones?', 'Is my pulse normal?', 'What can help me sleep better tonight?']

export default function AskCanary({ onClose }: { onClose: () => void }) {
  const { me, catalog, setEmergency, askSeed, clearAskSeed, toast } = useSession()
  const navigate = useNavigate()
  const [status, setStatus] = useState<AssistantStatus | null>(null)
  const [items, setItems] = useState<AssistantAnswer[]>([])
  const [busy, setBusy] = useState(false)
  const [loadErr, setLoadErr] = useState<string | null>(null)
  const sug = useAction()
  const act = useAction()
  const end = useRef<HTMLDivElement>(null)
  const drawer = useRef<HTMLElement>(null)

  // Focus the question when the drawer opens; Escape closes it, as the close button does.
  useEffect(() => { drawer.current?.querySelector<HTMLInputElement>('form input')?.focus() }, [])
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  useEffect(() => {
    api.assistantStatus().then(setStatus).catch(() => setLoadErr('Could not reach the assistant. Questions will not work until the connection is back.'))
    if (me) api.askHistory(me).then(setItems).catch(() => setLoadErr('Could not load your earlier questions.'))
  }, [me])
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }) }, [items])

  /** Sends one question. Throws when it is refused or the server is down: the caller shows the message. */
  const ask = async (text: string) => {
    if (!me) throw new Error('Enter your space first: Canary answers only about your own data.')
    setBusy(true)
    try {
      const r = await api.ask(me, text)
      // A new answer does not come back with asked_by; the medical token is what the server records it from.
      setItems(x => [...x, { ...r, question: text, asked_by: r.asked_by ?? (api.isMedical() ? 'medical' : 'self') }])
    } catch (e) {
      // 429: the per-person limit on questions (assistant/limits.py). The server's message says how long to wait.
      if (e instanceof ApiError && e.status === 429) throw new Error(`Too many questions in a short time. ${e.message}`)
      throw e
    } finally { setBusy(false) }
  }
  // An alert's "Ask why" opens the drawer with its question: ask it once, then forget it.
  useEffect(() => {
    if (!askSeed || !me) return
    const q = askSeed
    clearAskSeed()
    sug.run(() => ask(q))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [askSeed, me])
  const form = useForm({
    initial: { q: '' },
    validate: f => ({ q: v.length('Question', { max: 500 })(f.q) }),
    submit: async f => { await ask(f.q.trim()); form.reset({ q: '' }) },
  })
  // Title, version and excerpt for every kb: id the backend described, across the whole conversation.
  const meta: Record<string, SourceMeta> = Object.assign({}, ...items.map(a => a.source_meta ?? {}))
  const label = (id: string) => {
    const parts = id.split(':')
    const [kind, a, b] = parts
    if (kind === 'telemetry') return catalog?.indicators[b]?.name ?? b
    if (kind === 'card' && a === 'hazard') return `Hazard: ${HAZARD_NAMES[b] ?? b}`
    if (kind === 'card' && a === 'risk') return `Risk: ${RISK_NAMES[b] ?? b}`
    if (kind === 'card') return `${catalog?.systems[a]?.name ?? a} card`
    if (kind === 'risk') { const r = parts.find(p => RISK_NAMES[p]); return r ? `Risk: ${RISK_NAMES[r]}` : 'Risk' }
    if (kind === 'dose') return 'Your dose'
    if (kind === 'recipe') return 'Measurement recipe'
    if (kind === 'emergency') return 'Guided Response record'
    if (kind === 'protocol') return `protocol ${a}`
    if (kind === 'nasa') {  // nasa:std3001v1:V14002 -> NASA-STD-3001 V1 4002
      const std = /^std(\d+)v\d+$/.exec(a ?? ''), item = /^V(\d)(\d{4})$/.exec(b ?? '')
      return std && item ? `NASA-STD-${std[1]} V${item[1]} ${item[2]}` : `NASA ${a.toUpperCase()}`
    }
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
    const btn = (fn: () => void | Promise<void>) => <button className="btn sm pri ask-action" disabled={act.busy} onClick={() => act.run(async () => { await fn() })}>{ra.label}</button>
    if (kind === 'goal') return btn(() => { onClose(); navigate('/me/goals') })
    if (kind === 'protocol') return btn(() => { onClose(); setEmergency(arg || true) })
    if (kind === 'send_briefing' && me) return btn(async () => {
      await api.briefing(me)
      toast('Briefing draft ready. The medical team approves it before it is queued for Earth.')
    })
    const why = kind === 'contact_cmo' ? 'Talk to the crew medical officer in person or over crew comms. Messaging from here is not available yet.'
      : medical ? `This action (${ra.id}) is not available here yet.` : 'This action is not available here yet.'
    return <button className="btn sm ask-action" disabled title={why} aria-disabled="true">{ra.label}</button>
  }
  // Everyone here sees plain sentences only. Rule ids, guard exits and tool names stay in the medical audit (Medical console).
  const medical = api.isMedical()
  const guardNote = (g?: GuardReport) => {
    if (!g) return null
    const lines = plainGuard([...(g.rule_ids ?? []), ...(g.reason ? [g.reason.split(': ')[0]] : [])])
    return lines.length ? <div className="ask-guard small">{lines.map(l => <p key={l}>{l}</p>)}</div> : null
  }
  return (
    <>
      <div className="scrim soft ask-scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="ask-title" ref={drawer}>
        <div className="row drawer-head">
          <div>
            <h2 id="ask-title">Ask Canary</h2>
            <div className="small muted">Explains your data, with a source for each answer. Never diagnoses.</div>
          </div>
          <button className="btn sm ghost right" onClick={onClose} aria-label="Close Ask Canary"><Icon name="close" size={15} /></button>
        </div>
        <div className="drawer-body">
          <div className="slot">
            <div className="row"><span className="lbl">Assistant</span>
              <span className="tag right">{modelLine(status)}</span></div>
            {status?.warning && <p className="small err" role="alert" style={{ marginTop: 6 }}>{status.warning}</p>}
          </div>
        </div>
        <div className="chat" role="log" aria-live="polite">
          {!me && <p className="muted small"><b className="ink">Open My space first.</b> Canary answers only about your own data.</p>}
          {me && !items.length && <p className="muted small">Ask about your numbers, a body system or what to do today. For an emergency, hold the red button.</p>}
          {items.map(a => (
            <div key={a.id} className="col" style={{ gap: 8 }}>
              {a.asked_by === 'medical' && <span className="tag ask-who">Asked by the medical team</span>}
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
                {a.recommended_action && action(a.recommended_action)}
                {a.mode === 'emergency' && !a.recommended_action && <button className="btn sm" style={{ marginTop: 10 }} onClick={() => { onClose(); setEmergency(true) }}>Open Guided Response</button>}
                {guardNote(a.guard)}
              </div>
            </div>
          ))}
          {loadErr && <p className="small err" role="alert">{loadErr}</p>}
          {busy && <p className="lbl" role="status" aria-live="polite">Checking your data…</p>}
          <div ref={end} />
        </div>
        <div className="drawer-foot">
          <div className="row wrap drawer-suggest">{SUGGEST.map(s => <button key={s} className="btn sm" disabled={busy || !me} onClick={() => sug.run(() => ask(s))}>{s}</button>)}</div>
          <ActionError error={sug.error} />
          <ActionError error={act.error} />
          <p className="small muted ask-disclosure">The medical team can read what you ask here.</p>
          <form noValidate onSubmit={form.submit}>
            <div className="row ask-row">
              <div className="grow"><Field form={form} name="q" label="Your question" hideLabel placeholder="Ask about your health data…" hint="Up to 500 characters" maxLength={500} autoComplete="off" disabled={!me} /></div>
              <button className="btn pri" disabled={busy || form.busy || !me} aria-label="Send"><Icon name="send" size={15} /></button>
            </div>
            <FormError form={form} />
          </form>
        </div>
      </aside>
    </>
  )
}
