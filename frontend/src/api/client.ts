// Thin typed client for the Canary API. Every screen talks to the backend through here.
import type {
  AlertEvent, AlertEvents, AssistantAnswer, AssistantAuditEntry, AssistantStatus, Briefing, Catalog, CrewDetail, CrewList, CrewOverview, Emergency, OpenEmergency, GoalsResponse,
  CheckinResult, ControlDemo, GroundForm, PublicAccounts, RegisterOptions, DataStatus, ImportResult, NewSpaceEvent, SpaceEvent, ControlOverview, Leaderboard, Leg, MedGoal, MissionForm, MissionOverview, SeatForm, MedicalOverview, Message, Mission, Scene, PersonalRecord, Plan, PlanConditions, Protocols, ProtocolLibrary, ProtocolMatch, Suggestions, TestHistory, Rad, SpaceWeather,
  CareEvent, CorrectionRequest,
} from './types'

/** One kind of sign-in per console: crew (a private space), medical (the medical console) or control (Canary Control). */
export type Kind = 'crew' | 'medical' | 'control'

// One token store, kept for this browser tab. Every call sends one `Authorization: Bearer` token: the one that fits the call.
const STORE = 'canary.tokens'
let tokens: Partial<Record<Kind, string>> = readTokens()

function readTokens(): Partial<Record<Kind, string>> {
  try { return JSON.parse(sessionStorage.getItem(STORE) ?? '{}') } catch { return {} }
}

function setToken(kind: Kind, token: string | null) {
  const next = { ...tokens }
  if (token === null) delete next[kind]; else next[kind] = token
  tokens = next
  try { Object.keys(next).length ? sessionStorage.setItem(STORE, JSON.stringify(next)) : sessionStorage.removeItem(STORE) } catch { /* private mode */ }
}

/** Calls only one kind of sign-in can make, by path; everything else follows the screen the person is on. */
function kindFor(path: string, method: string): Kind | null {
  if (path.startsWith('/control') || path.startsWith('/demo/') || path.startsWith('/setup') || (method !== 'GET' && (path.startsWith('/plan') || path === '/mission'))) return 'control'
  if (path.startsWith('/medical/')) return 'medical'
  const here = typeof location === 'undefined' ? '' : location.pathname
  if (here.startsWith('/control')) return 'control'
  if (here.startsWith('/medical') || (here.startsWith('/crew/') && tokens.medical)) return 'medical'
  return null
}

/** The token a call carries: the kind it needs, else the crew sign-in, else the medical one (the crew pages a medical person reads). */
function pick(path: string, method: string, as?: Kind): { kind: Kind; token: string } | null {
  const want = as ?? kindFor(path, method)
  const kind = want ?? (tokens.crew ? 'crew' : tokens.medical ? 'medical' : tokens.control ? 'control' : null)
  const token = kind ? tokens[kind] : undefined
  return kind && token ? { kind, token } : null
}

/** The token carries `{kind}.{id}.{roles}.{exp}.{jti}.{sig}`. A 403 on your own space, or any 401/403 after expiry, means it no longer works. */
function sessionLost(path: string, status: number, token: string): boolean {
  const [, id, , exp] = token.split('.')
  if (Number(exp) * 1000 < Date.now()) return true
  const otherPerson = /^\/crew\/([a-z]+)$/.exec(path)
  return status === 403 && !(otherPerson && otherPerson[1] !== id)
}

/** Whether the server answered the last call (any HTTP answer counts). The offline banner listens for `canary:connection`. */
let reachable = true
function reach(ok: boolean) {
  if (reachable === ok) return
  reachable = ok
  window.dispatchEvent(new CustomEvent('canary:connection', { detail: ok }))
}

async function req<T>(path: string, init?: RequestInit & { as?: Kind }): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const sent = pick(path, init?.method ?? 'GET', init?.as)
  if (sent) headers.Authorization = `Bearer ${sent.token}`
  if (init?.body instanceof FormData) delete headers['Content-Type']
  let r: Response
  try {
    r = await fetch(`/api${path}`, { ...init, headers: { ...headers, ...(init?.headers as Record<string, string>) } })
  } catch {
    reach(false)
    throw new ApiError(0, 'Canary is not reachable. Check the connection to the ship\'s server.')
  }
  reach(true)
  if (!r.ok) {
    let detail: unknown = r.statusText
    try { detail = (await r.json()).detail ?? detail } catch { /* not json */ }
    if (sent?.kind === 'crew' && sent.token === tokens.crew && (r.status === 401 || r.status === 403) && !/\/(session|pin)$/.test(path) && sessionLost(path, r.status, sent.token)) {
      setToken('crew', null)
      window.dispatchEvent(new Event('canary:locked'))
    }
    const issues = issuesOf(detail)
    throw new ApiError(r.status, issues.length ? issues.map(i => i.message).join('. ') : r.status >= 500 ? 'The server had a problem with this request. Try again in a moment.' : String(detail), issues)
  }
  return r.json() as Promise<T>
}

/** One thing wrong with one field. `field` is a dotted path such as `crew.1.dob`, or `form` for the whole form. */
export interface FieldIssue { field: string; message: string }

/** Reads the two shapes the API sends: `[{field, message}]` and FastAPI's own `[{loc, msg}]`. */
function issuesOf(detail: unknown): FieldIssue[] {
  if (!Array.isArray(detail)) return []
  return detail.flatMap((d): FieldIssue[] => {
    if (d && typeof d === 'object') {
      const o = d as Record<string, unknown>
      if (typeof o.message === 'string') return [{ field: String(o.field ?? 'form'), message: o.message }]
      if (typeof o.msg === 'string') return [{ field: Array.isArray(o.loc) ? o.loc.filter(x => x !== 'body').join('.') : 'form', message: o.msg }]
    }
    return []
  })
}

export class ApiError extends Error {
  /** `status` is 0 when the server could not be reached. `issues` is set for 400/422 answers that name fields. */
  constructor(public status: number, message: string, public issues: FieldIssue[] = []) { super(message) }
}

/** The sentence to show a person for any thrown value. */
export function errorText(e: unknown): string {
  return e instanceof Error && e.message ? e.message : 'Something went wrong. Try again.'
}

/** Ask the server to revoke a token (POST /api/session/logout). Best effort: the token is dropped here either way. */
function endSession(kind: Kind) {
  const token = tokens[kind]
  if (!token) return
  fetch('/api/session/logout', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }).catch(() => undefined)
  setToken(kind, null)
}

const body = (b: unknown) => ({ body: JSON.stringify(b) })

export const api = {
  catalog: () => req<Catalog>('/catalog'),
  mission: () => req<Mission>('/mission'),
  scenes: () => req<Scene[]>('/scenes'),
  setStep: (step: number) => req<Mission>('/mission', { method: 'PUT', ...body({ step }) }),
  setLocation: (location: string | null) =>
    req<Mission>('/mission', { method: 'PUT', ...body(location ? { location } : { clear_location: true }) }),
  reset: () => req<Mission>('/demo/reset', { method: 'POST' }),
  /** Demo only, no sign-in: wipe to nothing registered (the tour registers from the start). */
  demoStartEmpty: () => req<{ registered: boolean }>('/demo/start-empty', { method: 'POST' }),
  /** Demo only, no sign-in, only while nothing is registered: load the demo mission (skipping the intro). */
  demoQuickstart: () => req<{ registered: boolean }>('/demo/quickstart', { method: 'POST' }),
  setDay: (day: number | null) => req<Mission>('/mission', { method: 'PUT', ...body(day === null ? { clear_day: true } : { day }) }),
  plan: () => req<Plan>('/plan'),
  conditions: () => req<PlanConditions>('/plan/conditions'),
  savePlan: (name: string, legs: Leg[]) => req<Plan>('/plan', { method: 'PUT', ...body({ name, legs }) }),
  usePreset: (preset: string) => req<Plan>('/plan/preset', { method: 'POST', ...body({ preset }) }),

  /** Sign in to a private space with the 4-digit PIN. Stores the session token and returns it. */
  crewSignIn: async (id: string, pin: string) => {
    const r = await req<{ token: string; expires_at: number; crew_id: string }>(`/crew/${id}/session`, { method: 'POST', ...body({ pin }) })
    setToken('crew', r.token)
    return r.token
  },
  crewSignOut: () => endSession('crew'),
  hasCrewSession: () => tokens.crew !== undefined,
  /** Anyone signed in to any console. Crew overview, leaderboard and photos need a sign-in: calls are made only then. */
  signedIn: () => Object.keys(tokens).length > 0,
  changePin: (id: string, current: string, next: string) =>
    req<{ changed: boolean }>(`/crew/${id}/pin`, { method: 'PUT', ...body({ current, new: next }) }),
  crew: () => req<CrewList>('/crew'),
  overview: () => req<CrewOverview>('/crew/overview'),
  photos: () => req<Record<string, string>>('/crew/photos'),
  setPhoto: (id: string, data_url: string) => req<Record<string, string>>(`/crew/${id}/photo`, { method: 'PUT', ...body({ data_url }) }),
  deletePhoto: (id: string) => req<Record<string, string>>(`/crew/${id}/photo`, { method: 'DELETE' }),
  crewDetail: (id: string) => req<CrewDetail>(`/crew/${id}`),
  goals: (id: string) => req<GoalsResponse>(`/goals/${id}`),
  setGoal: (id: string, goal: string, done: boolean) => req<GoalsResponse>(`/goals/${id}/${goal}`, { method: 'POST', ...body({ done }) }),
  leaderboard: () => req<Leaderboard>('/leaderboard'),
  checkin: (crew_id: string, kind: string, payload: Record<string, unknown>, photo?: string, origin?: 'sample') =>
    req<CheckinResult>('/checkins', { method: 'POST', ...body({ crew_id, kind, payload, ...(photo ? { photo } : {}), ...(origin ? { origin } : {}) }) }),
  /** The photo of the display kept with a vitals check-in: the person and the medical team only. */
  checkinPhoto: (crew_id: string, id: number) => req<{ data_url: string }>(`/checkins/${crew_id}/${id}/photo`),
  checkins: (crew_id: string) => req<TestHistory>(`/checkins/${crew_id}`),
  record: (crew_id: string) => req<PersonalRecord>(`/crew/${crew_id}/record`),
  suggestions: (crew_id: string) => req<Suggestions>(`/suggestions/${crew_id}`),
  dismissSuggestion: (crew_id: string, sid: string) => req<Suggestions>(`/suggestions/${crew_id}/${sid}/dismiss`, { method: 'POST' }),
  acceptSuggestion: (crew_id: string, sid: string) => req<Suggestions>(`/suggestions/${crew_id}/${sid}/accept`, { method: 'POST' }),

  protocols: () => req<Protocols>('/protocols'),
  protocolLibrary: () => req<ProtocolLibrary>('/protocols/library'),
  matchProtocol: (text: string) => req<ProtocolMatch>('/protocols/match', { method: 'POST', ...body({ text }) }),
  startEmergency: (responder: string | null, token?: string) => req<Emergency>('/emergencies', { method: 'POST', ...body({ responder, token }) }),
  emergenciesOpen: () => req<OpenEmergency[]>('/emergencies/open'),
  emergencyEvent: (id: number, e: { text?: string; protocol?: string; patient?: string; outcome?: string; close?: boolean; cancel?: boolean; escalate?: boolean }) =>
    req<Emergency>(`/emergencies/${id}`, { method: 'POST', ...body(e) }),

  messages: (crew_id?: string) => req<Message[]>(`/messages${crew_id ? `?crew_id=${crew_id}` : ''}`),
  /** The sender is whoever is signed in. `as` sends only that console's token, so the message is from that person. */
  send: (as: Kind, recipient: string, text: string) => req<Message[]>('/messages', { method: 'POST', as, ...body({ recipient, text }) }),
  accountsPublic: () => req<PublicAccounts>('/accounts/public'),

  spaceWeather: () => req<SpaceWeather>('/space-weather'),
  rad: () => req<Rad>('/nasa/rad'),

  assistantStatus: () => req<AssistantStatus>('/assistant/status'),
  ask: (crew_id: string, question: string) => req<AssistantAnswer>('/assistant/ask', { method: 'POST', ...body({ crew_id, question }) }),
  askHistory: (crew_id: string) => req<AssistantAnswer[]>(`/assistant/history/${crew_id}`),
  briefing: (crew_id: string) => req<Briefing>('/briefings', { method: 'POST', ...body({ crew_id }) }),
  approveBriefing: (id: number) => req<Briefing>(`/briefings/${id}/approve`, { method: 'POST' }),
  briefings: (crew_id: string) => req<Briefing[]>(`/briefings/${crew_id}`),

  medicalSignIn: async (account_id: string, pin: string) => {
    const r = await req<{ token: string }>('/medical/session', { method: 'POST', ...body({ account_id, pin }) })
    setToken('medical', r.token)
    return true
  },
  medicalSignOut: () => endSession('medical'),
  isMedical: () => tokens.medical !== undefined,

  missionOverview: () => req<MissionOverview>('/mission/overview'),
  /** An MCC account and its PIN; without `account_id`, the first-access PIN (only until an MCC account is registered). */
  controlSignIn: async (pin: string, account_id?: string) => {
    const r = await req<{ token: string }>('/control/session', { method: 'POST', ...body(account_id ? { account_id, pin } : { pin }) })
    setToken('control', r.token)
  },
  controlSignOut: () => endSession('control'),
  isControl: () => tokens.control !== undefined,
  controlOverview: () => req<ControlOverview>('/control/overview'),
  controlDemo: () => req<ControlDemo>('/control/demo'),
  controlOptions: () => req<RegisterOptions>('/control/register-options'),
  controlRegister: (crew: SeatForm[], mission: MissionForm, ground: GroundForm[]) => req<ControlOverview>('/control/register', { method: 'POST', ...body({ crew, mission, ground }) }),
  controlDataStatus: () => req<DataStatus>('/control/data-status'),
  controlSpaceEvents: () => req<{ events: SpaceEvent[] }>('/control/space-events'),
  controlAddSpaceEvent: (e: NewSpaceEvent) => req<SpaceEvent>('/control/space-events', { method: 'POST', ...body(e) }),
  /** Date and time of a simulated mission clock, or `{ real: true }` to follow today's date in UTC. */
  controlSetClock: (c: { date: string; time?: string } | { real: true }) => req<Mission>('/control/clock', { method: 'PUT', ...body(c) }),
  /** A bundled mission package by name, or files (a .zip, or CSV files named like the package files) the person chose. */
  controlImport: (what: { package: string } | { files: File[] }) => {
    if ('package' in what) return req<ImportResult>('/control/import', { method: 'POST', ...body(what) })
    const form = new FormData()
    for (const f of what.files) form.append('file', f, f.name)
    // req leaves the Content-Type out for a FormData body: the browser adds the multipart boundary
    return req<ImportResult>('/control/import', { method: 'POST', body: form, })
  },
  controlDemoData: () => req<ControlOverview>('/control/demo-data', { method: 'POST' }),
  medicalOverview: () => req<MedicalOverview>('/medical/overview'),
  setThresholds: (watch: number, act: number) => req<{ watch: number; act: number }>('/medical/thresholds', { method: 'PUT', ...body({ watch, act }) }),
  assistantAudit: (limit = 30) => req<AssistantAuditEntry[]>(`/medical/assistant-audit?limit=${limit}`),
  medGoals: () => req<MedGoal[]>('/medical/goals'),
  addMedGoal: (g: { who: string; area: string; title: string; why: string; days: number }) =>
    req<MedGoal[]>('/medical/goals', { method: 'POST', ...body(g) }),
  /** Health records are never deleted: this voids the goal, and the server refuses it without a reason. */
  delMedGoal: (id: number, reason: string) => req<MedGoal[]>(`/medical/goals/${id}`, { method: 'DELETE', ...body({ reason }) }),
  /** Stored alert events: all of them for the medical console, ids and levels only for Canary Control. */
  alertEvents: (openOnly = true) => req<AlertEvents>(`/alerts/events?open_only=${openOnly}`),
  /** The crew medical officer or a flight surgeon acknowledges an alert event (stops its escalation). */
  ackAlert: (id: number) => req<AlertEvent>(`/alerts/events/${id}/ack`, { method: 'POST' }),
  /** The medical team records the review of a care window that is awaiting review (EMG-04). */
  reviewCareWindow: (eid: number, resolution: string) => req<CareEvent>(`/medical/care-windows/${eid}/review`, { method: 'POST', ...body({ resolution }) }),
  /** Medical team or Canary Control corrects a height (EDIT-01). The old value stays on record with the reason. */
  correctHeight: (crew_id: string, value: number, reason: string) => req<unknown>(`/corrections/crew/${crew_id}/height`, { method: 'PUT', ...body({ value, reason }) }),
  /** Medical team or Canary Control corrects one measurement by its observation id (EDIT-01). */
  correctMeasurement: (obs_id: number, value: number, reason: string) => req<unknown>(`/corrections/measurements/${obs_id}`, { method: 'PUT', ...body({ value, reason }) }),
  /** The crew member asks for a correction to their own record. Nothing changes until the medical team acts on it. */
  requestCorrection: (crew_id: string, r: { field: string; target?: string | null; proposed?: unknown; reason: string }) =>
    req<{ id: number; status: string }>(`/crew/${crew_id}/corrections`, { method: 'POST', ...body(r) }),
  /** Open correction requests, oldest first (medical team or Canary Control). */
  corrections: () => req<{ requests: CorrectionRequest[] }>('/corrections'),
}
