// Thin typed client for the Canary API. Every screen talks to the backend through here.
import type {
  AssistantAnswer, AssistantStatus, Briefing, Catalog, CrewDetail, CrewList, CrewOverview, Emergency, GoalsResponse,
  Leaderboard, Leg, MedGoal, MedicalOverview, Message, Mission, Plan, PlanConditions, Protocols, TestHistory, Rad, SpaceWeather,
} from './types'

let medicalToken: string | null = sessionStorageGet('canary.med')
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
  const sent = viewerToken
  if (sent) headers['X-Canary-Viewer'] = sent
  const r = await fetch(`/api${path}`, { ...init, headers: { ...headers, ...(init?.headers as Record<string, string>) } })
  if (!r.ok) {
    let detail = r.statusText
    try { detail = (await r.json()).detail ?? detail } catch { /* not json */ }
    if (sent && sent === viewerToken && (r.status === 401 || r.status === 403) && !/\/(session|pin)$/.test(path) && sessionLost(path, r.status, sent)) {
      storeViewer(null)
      window.dispatchEvent(new Event('canary:locked'))
    }
    throw new ApiError(r.status, String(detail))
  }
  return r.json() as Promise<T>
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

const body = (b: unknown) => ({ body: JSON.stringify(b) })

export const api = {
  catalog: () => req<Catalog>('/catalog'),
  mission: () => req<Mission>('/mission'),
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
  checkin: (crew_id: string, kind: string, payload: Record<string, unknown>) =>
    req<{ ok: boolean; summary: string; goal: string | null }>('/checkins', { method: 'POST', ...body({ crew_id, kind, payload }) }),
  checkins: (crew_id: string) => req<TestHistory>(`/checkins/${crew_id}`),

  protocols: () => req<Protocols>('/protocols'),
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
  medicalOverview: () => req<MedicalOverview>('/medical/overview'),
  setThresholds: (watch: number, act: number) => req<{ watch: number; act: number }>('/medical/thresholds', { method: 'PUT', ...body({ watch, act }) }),
  medGoals: () => req<MedGoal[]>('/medical/goals'),
  addMedGoal: (g: { who: string; area: string; title: string; why: string; days: number }) =>
    req<MedGoal[]>('/medical/goals', { method: 'POST', ...body(g) }),
  delMedGoal: (id: number) => req<MedGoal[]>(`/medical/goals/${id}`, { method: 'DELETE' }),
}
