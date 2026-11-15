// Thin typed client for the Canary API. Every screen talks to the backend through here.
import type {
  AssistantAnswer, AssistantStatus, Briefing, Catalog, CrewDetail, CrewList, CrewOverview, Emergency, GoalsResponse,
  CheckinResult, ControlDemo, DataStatus, ImportResult, NewSpaceEvent, SpaceEvent, ControlOverview, Leaderboard, Leg, MedGoal, MissionForm, MissionOverview, SeatForm, MedicalOverview, Message, Mission, Scene, PersonalRecord, Plan, PlanConditions, Protocols, ProtocolLibrary, ProtocolMatch, Suggestions, TestHistory, Rad, SpaceWeather,
} from './types'

let medicalToken: string | null = sessionStorageGet('canary.med')
// Mission Control (Canary Control) session: a separate token from a separate PIN.
let controlToken: string | null = sessionStorageGet('canary.ctl')
// Session token of whoever entered their private space on this terminal (from the 4-digit PIN sign-in).
let viewerToken: string | null = sessionStorageGet('canary.viewer')

function sessionStorageGet(k: string): string | null {
  try { return sessionStorage.getItem(k) } catch { return null }
}

function storeViewer(token: string | null) {
  viewerToken = token
  try { token === null ? sessionStorage.removeItem('canary.viewer') : sessionStorage.setItem('canary.viewer', token) } catch { /* private mode */ }
}

/** The token carries `{id}.{exp}.{sig}`. A 403 on your own space, or any 401/403 after expiry, means it no longer works. */
function sessionLost(path: string, status: number, token: string): boolean {
  const [id, exp] = token.split('.')
  if (Number(exp) * 1000 < Date.now()) return true
  const otherPerson = /^\/crew\/([a-z]+)$/.exec(path)
  return status === 403 && !(otherPerson && otherPerson[1] !== id)
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (medicalToken) headers.Authorization = `Bearer ${medicalToken}`
  if (controlToken) headers['X-Canary-Control'] = controlToken
  const sent = viewerToken
  if (sent) headers['X-Canary-Viewer'] = sent
  if (init?.body instanceof FormData) delete headers['Content-Type']
  let r: Response
  try {
    r = await fetch(`/api${path}`, { ...init, headers: { ...headers, ...(init?.headers as Record<string, string>) } })
  } catch {
    throw new ApiError(0, 'Cannot reach the Canary server. Check the connection and try again.')
  }
  if (!r.ok) {
    let detail: unknown = r.statusText
    try { detail = (await r.json()).detail ?? detail } catch { /* not json */ }
    if (sent && sent === viewerToken && (r.status === 401 || r.status === 403) && !/\/(session|pin)$/.test(path) && sessionLost(path, r.status, sent)) {
      storeViewer(null)
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

const body = (b: unknown) => ({ body: JSON.stringify(b) })

export const api = {
  catalog: () => req<Catalog>('/catalog'),
  mission: () => req<Mission>('/mission'),
  scenes: () => req<Scene[]>('/scenes'),
  setStep: (step: number) => req<Mission>('/mission', { method: 'PUT', ...body({ step }) }),
  setLocation: (location: string | null) =>
    req<Mission>('/mission', { method: 'PUT', ...body(location ? { location } : { clear_location: true }) }),
  reset: () => req<Mission>('/demo/reset', { method: 'POST' }),
  setDay: (day: number | null) => req<Mission>('/mission', { method: 'PUT', ...body(day === null ? { clear_day: true } : { day }) }),
  plan: () => req<Plan>('/plan'),
  conditions: () => req<PlanConditions>('/plan/conditions'),
  savePlan: (name: string, legs: Leg[]) => req<Plan>('/plan', { method: 'PUT', ...body({ name, legs }) }),
  usePreset: (preset: string) => req<Plan>('/plan/preset', { method: 'POST', ...body({ preset }) }),

  /** Sign in to a private space with the 4-digit PIN. Stores the session token and returns it. */
  crewSignIn: async (id: string, pin: string) => {
    const r = await req<{ token: string; expires_at: number; crew_id: string }>(`/crew/${id}/session`, { method: 'POST', ...body({ pin }) })
    storeViewer(r.token)
    return r.token
  },
  crewSignOut: () => storeViewer(null),
  changePin: (id: string, current: string, next: string) =>
    req<{ changed: boolean }>(`/crew/${id}/pin`, { method: 'PUT', ...body({ current, new: next }) }),
  setup: (name: string, legs: Leg[]) => req<Mission>('/setup', { method: 'POST', ...body({ name, legs }) }),
  crew: () => req<CrewList>('/crew'),
  overview: () => req<CrewOverview>('/crew/overview'),
  photos: () => req<Record<string, string>>('/crew/photos'),
  setPhoto: (id: string, data_url: string) => req<Record<string, string>>(`/crew/${id}/photo`, { method: 'PUT', ...body({ data_url }) }),
  deletePhoto: (id: string) => req<Record<string, string>>(`/crew/${id}/photo`, { method: 'DELETE' }),
  crewDetail: (id: string) => req<CrewDetail>(`/crew/${id}`),
  goals: (id: string) => req<GoalsResponse>(`/goals/${id}`),
  setGoal: (id: string, goal: string, done: boolean) => req<GoalsResponse>(`/goals/${id}/${goal}`, { method: 'POST', ...body({ done }) }),
  leaderboard: () => req<Leaderboard>('/leaderboard'),
  checkin: (crew_id: string, kind: string, payload: Record<string, unknown>, photo?: string) =>
    req<CheckinResult>('/checkins', { method: 'POST', ...body({ crew_id, kind, payload, ...(photo ? { photo } : {}) }) }),
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
  startEmergency: (responder: string | null) => req<Emergency>('/emergencies', { method: 'POST', ...body({ responder }) }),
  emergencyEvent: (id: number, e: { text?: string; protocol?: string; patient?: string; outcome?: string; close?: boolean }) =>
    req<Emergency>(`/emergencies/${id}`, { method: 'POST', ...body(e) }),

  messages: (crew_id?: string) => req<Message[]>(`/messages${crew_id ? `?crew_id=${crew_id}` : ''}`),
  send: (sender: string, recipient: string, text: string) => req<Message[]>('/messages', { method: 'POST', ...body({ sender, recipient, text }) }),

  spaceWeather: () => req<SpaceWeather>('/space-weather'),
  rad: () => req<Rad>('/nasa/rad'),

  assistantStatus: () => req<AssistantStatus>('/assistant/status'),
  ask: (crew_id: string, question: string) => req<AssistantAnswer>('/assistant/ask', { method: 'POST', ...body({ crew_id, question }) }),
  askHistory: (crew_id: string) => req<AssistantAnswer[]>(`/assistant/history/${crew_id}`),
  briefing: (crew_id: string) => req<Briefing>('/briefings', { method: 'POST', ...body({ crew_id }) }),
  approveBriefing: (id: number) => req<Briefing>(`/briefings/${id}/approve`, { method: 'POST' }),
  briefings: (crew_id: string) => req<Briefing[]>(`/briefings/${crew_id}`),

  medicalSignIn: async (pin: string) => {
    const r = await req<{ token: string }>('/medical/session', { method: 'POST', ...body({ pin }) })
    medicalToken = r.token
    try { sessionStorage.setItem('canary.med', r.token) } catch { /* private mode */ }
    return true
  },
  medicalSignOut: () => {
    medicalToken = null
    try { sessionStorage.removeItem('canary.med') } catch { /* private mode */ }
  },
  isMedical: () => medicalToken !== null,

  missionOverview: () => req<MissionOverview>('/mission/overview'),
  controlSignIn: async (pin: string) => {
    const r = await req<{ token: string }>('/control/session', { method: 'POST', ...body({ pin }) })
    controlToken = r.token
    try { sessionStorage.setItem('canary.ctl', r.token) } catch { /* private mode */ }
  },
  controlSignOut: () => { controlToken = null; try { sessionStorage.removeItem('canary.ctl') } catch { /* private mode */ } },
  isControl: () => controlToken !== null,
  controlOverview: () => req<ControlOverview>('/control/overview'),
  controlDemo: () => req<ControlDemo>('/control/demo'),
  controlRegister: (crew: SeatForm[], mission: MissionForm) => req<ControlOverview>('/control/register', { method: 'POST', ...body({ crew, mission }) }),
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
  controlClear: () => req<ControlOverview>('/control/clear', { method: 'POST' }),
  controlDemoData: () => req<ControlOverview>('/control/demo-data', { method: 'POST' }),
  medicalOverview: () => req<MedicalOverview>('/medical/overview'),
  setThresholds: (watch: number, act: number) => req<{ watch: number; act: number }>('/medical/thresholds', { method: 'PUT', ...body({ watch, act }) }),
  medGoals: () => req<MedGoal[]>('/medical/goals'),
  addMedGoal: (g: { who: string; area: string; title: string; why: string; days: number }) =>
    req<MedGoal[]>('/medical/goals', { method: 'POST', ...body(g) }),
  delMedGoal: (id: number) => req<MedGoal[]>(`/medical/goals/${id}`, { method: 'DELETE' }),
}
