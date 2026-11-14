// Thin typed client for the Canary API. Every screen talks to the backend through here.
import type {
  AssistantAnswer, AssistantStatus, Briefing, Catalog, CrewDetail, CrewList, Emergency, GoalsResponse,
  Leaderboard, MedGoal, MedicalOverview, Message, Mission, Protocols, Rad, SpaceWeather,
} from './types'

let medicalToken: string | null = sessionStorageGet('canary.med')

function sessionStorageGet(k: string): string | null {
  try { return sessionStorage.getItem(k) } catch { return null }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (medicalToken) headers.Authorization = `Bearer ${medicalToken}`
  const r = await fetch(`/api${path}`, { ...init, headers: { ...headers, ...(init?.headers as Record<string, string>) } })
  if (!r.ok) {
    let detail = r.statusText
    try { detail = (await r.json()).detail ?? detail } catch { /* not json */ }
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

  crew: () => req<CrewList>('/crew'),
  crewDetail: (id: string) => req<CrewDetail>(`/crew/${id}`),
  goals: (id: string) => req<GoalsResponse>(`/goals/${id}`),
  setGoal: (id: string, goal: string, done: boolean) => req<GoalsResponse>(`/goals/${id}/${goal}`, { method: 'POST', ...body({ done }) }),
  leaderboard: () => req<Leaderboard>('/leaderboard'),
  checkin: (crew_id: string, kind: 'mood' | 'pvt' | 'amsler' | 'vitals', payload: Record<string, unknown>) =>
    req<{ ok: boolean }>('/checkins', { method: 'POST', ...body({ crew_id, kind, payload }) }),

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
  addMedGoal: (g: { who: string; area: string; title: string; why: string; days: number; xp: number }) =>
    req<MedGoal[]>('/medical/goals', { method: 'POST', ...body(g) }),
  delMedGoal: (id: number) => req<MedGoal[]>(`/medical/goals/${id}`, { method: 'DELETE' }),
}
