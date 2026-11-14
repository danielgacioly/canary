// Shapes returned by the Canary API (backend/canary/main.py). Keep in sync with the backend.
export type Level = 0 | 1 | 2
export type Area = 'physical' | 'mental'

export interface Place {
  id: string; name: string; sub: string; gravity_key: string; gravity: string
  delay_s: number; reply: string; hospital: string; dose_rate: number; what: string
}
export interface StoryStep { loc: string; day: number; me: string; storm: string | null; when: string; text: string }
export interface Leg { location: string; start: number; end: number; label: string }
export interface LegNow extends Leg { index: number; day_in_leg: number; length: number; next: Leg | null; days_to_next: number | null }
export interface Plan { name: string; legs: Leg[]; preset: string | null; presets: Record<string, string> }
export interface Mission {
  step: number; steps: number; story: StoryStep; day: number; day_label: string
  location: string; place: Place; storm: string | null; suggested_user: string; learning: boolean
  leg: LegNow; custom_day: boolean; location_override: boolean; plan_name: string; setup_done: boolean
}
export interface CrewInfo { id: string; name: string; role: string; initials: string; home: string; age: number }
export interface IndicatorDef { name: string; unit: string; area: Area; facet?: string; dir: string; sd: number; dp: number }
export interface SystemDef { name: string; area: Area; indicators: string[]; space: string; hazard: string }
export interface Source { id: string; name: string; org: string; url: string; used_for: string }
export interface Catalog {
  locations: Record<string, Omit<Place, 'id'>>; indicators: Record<string, IndicatorDef>
  systems: Record<string, SystemDef>; region_system: Record<string, string>
  crew: CrewInfo[]; story: StoryStep[]; sources: Source[]
}
export interface Indicator {
  id: string; name: string; unit: string; area: Area; facet?: string; dp: number
  value: number; baseline: number; delta: number; z: number; bad: number; level: Level; source: string
}
export interface SystemState { id: string; name: string; area: Area; level: Level; status: string; indicators: string[]; note: string | null }
export interface AlertGoal { id: string; area: Area; title: string }
export interface Alert {
  id: string; level: Level; title: string; why: string; todo: string[]; sys?: string | null
  protocol?: string; test?: string; env?: boolean; sources: string[]; goals: AlertGoal[]
}
export interface AreaState { score: number; level: Level; status: string }
export interface Dose { mission_msv: number; rate_msv_day: number; career_limit_msv: number; pct_of_limit: number; simulated: boolean }
export interface Goal {
  id: string; area: Area; title: string; why: string; sys?: string | null
  action?: string | null; by: 'routine' | 'alert' | 'medical' | 'suggestion'; done: boolean
}
export interface Badge { id: string; name: string; desc: string; area: string; progress: number; need: number; earned: boolean }
export interface Profile {
  crew_id: string; goals_week: number; goals_week_by_area: Record<Area, number>; streak: number; completion_7d: number
  badges: Badge[]; badges_earned: number; daily_done: [number, number, number][]; rank?: number
  name?: string; initials?: string; role?: string
}
export interface TeamGoal {
  id: string; area: Area; title: string; target: number; unit: string
  value: number; pct: number; done: boolean; contrib: Record<string, number>
}
export interface CrewSummary {
  id: string; name: string; role: string; initials: string; home: string
  areas: Record<Area, AreaState>; level: Level; status: string; top_alert: string | null; alerts: number
  ops: Ops; systems: Record<string, Level>; goals_week: number; streak: number
}
export interface CrewList {
  mission: Mission; crew: CrewSummary[]; team: TeamGoal[]; dose: Dose
  space_weather: { headline: string; active: boolean; kp_max: number; sep_events: number }
}
export interface Blood { subject: string; timepoints: string[]; lymphocytes: number[]; range: { min: number; max: number }; unit: string; note: string }
export interface CrewDetail {
  crew: CrewInfo; mission: Mission; indicators: Record<string, Indicator>; systems: Record<string, SystemState>
  alerts: Alert[]; areas: Record<Area, AreaState>; level: Level; status: string; dose: Dose
  trends: Record<string, [number, number][]>; goals: Goal[]; profile: Profile; blood: Blood
  events: { kind: string; day: number; payload: Record<string, unknown> }[]
  system_info: Record<string, { space: string; hazard: string }>
  ops: Ops; care_by: string; access: 'self' | 'medical'
}
export interface Ops { key: 'full' | 'limited' | 'rest'; label: string; level: Level }
export interface Person {
  id: string; name: string; role: string; initials: string; home: string
  today: { done: number; total: number; streak: number }
}
export interface Hazard { title: string; level: Level; what: string; sources: string[] }
export interface Ridge { id: 'R' | 'I' | 'D' | 'G' | 'E'; name: string; what: string; level: Level; label: string; here: string; systems: string[]; system_names: string[] }
export interface Warning { id: string; level: Level; title: string; why: string; todo: string[]; sources: string[] }
export interface LegConditions extends Leg { days: number; gravity_key: string; ridge: Ridge[]; dose_leg_msv: number }
export interface PlanConditions {
  name: string; legs: LegConditions[]; today: number; leg_index: number
  dose: { series: [number, number][]; now_msv: number; end_msv: number; limit_msv: number; simulated: boolean }
}
export interface ContractRow { info: string; self: string; doctor: string; crew: string; earth: string }
export interface CrewOverview {
  mission: Mission; people: Person[]; eva_open: boolean; hazards: Hazard[]
  team: TeamGoal[]; crew_streak: number; team_done: number; team_total: number; dose: Dose
  space_weather: { headline: string; active: boolean; kp_max: number; sep_events: number }
  contract: ContractRow[]; ridge: Ridge[]; warnings: Warning[]
}
export interface GoalsResponse { personal: Goal[]; team: TeamGoal[]; profile: Profile }
export interface Leaderboard { rows: Profile[]; team: TeamGoal[]; crew_goals_week: number; team_done: number; team_total: number }
export interface Step { i: number; t?: string; q?: string; yes?: number | string; no?: number | string; timer?: number; metro?: number; breath?: number; end?: number; variant?: string | null }
export interface Protocol { id: string; name: string; sign: string; kit: string[]; after: string[]; steps: Step[]; source: string }
export interface Protocols { order: string[]; protocols: Record<string, Protocol>; reviewed: boolean }
export interface Emergency { id: number; protocol: string | null; patient: string | null; responder: string | null; location: string; day: number; started_at: number; ended_at: number | null; outcome: string | null; log: [number, string][] }
export interface Message { id: number; sender: string; recipient: string; kind: string; text: string; sent_at: number; deliver_at: number; delivered: boolean; eta_s: number }
export interface Claim { text: string; source_ids: string[] }
// AI layer contract: docs/ai/schema.md §6 (backend/canary/assistant/contracts.py). New keys are optional so
// answers from the rule-based path (and older logs) still type-check.
export type AssistantMode = 'ai' | 'grounded' | 'refused' | 'emergency' | 'unknown' | 'fallback'
export type AssistantStatusValue = 'supported' | 'insufficient_evidence' | 'out_of_scope'
export interface Observation { statement: string; source_ids: string[] }
export type Explanation = Observation
export interface RecommendedAction { id: string; label: string }
export interface GuardReport { dropped_claims: number; rejected_numbers: string[]; reason: string | null }
export interface AssistantAnswer {
  id: number; mode: AssistantMode; provider: string; provider_error?: string | null
  answer: string; claims: Claim[]; sources: string[]; tools_used: { tool: string; args: Record<string, string> }[]; dropped: number
  question?: string
  status?: AssistantStatusValue
  observations?: Observation[]   // facts from data (telemetry, status, checkin, goals, summary, nasa)
  explanations?: Explanation[]   // possible explanations from approved knowledge (kb:)
  limitations?: string[]
  recommended_action?: RecommendedAction | null
  guard?: GuardReport
}
export interface AssistantStatus { provider: string; configured: boolean; available: string[]; entries: string[]; rules: string[]; tools: { name: string; description: string }[] }
export interface Briefing { id: number; crew_id: string; day: number; status: string; text: string; mode: string; bytes: number; created_at: number; deliver_at: number | null }
export interface SpaceWeather {
  mode: string; window: string; sep_events: number; kp_max: number; fast_cmes: number; flares: number
  kp: [string, number][]; sep: { t: string; i: string; n: number }[]; cme: { t: string; v: number; type: string }[]
  active: boolean; headline: string; live?: { window: string; sep_events: number; kp_max: number }
}
export interface Rad { quietMean: number; quiet: [number, number][]; storm: [number, number][]; unit: string; det: string; peak: number; ratio: number }
export interface MedicalOverview {
  mission: Mission; thresholds: { watch: number; act: number }; emergencies: Emergency[]
  crew: { id: string; name: string; role: string; level: Level; ops: Ops; areas: Record<Area, AreaState>; indicators: Record<string, Indicator>; systems: Record<string, SystemState>; alerts: Alert[] }[]
}
export interface MedGoal { id: number; who: string; area: Area; title: string; why: string; from_day: number; to_day: number }
export interface TestResult { kind: string; day: number; at: number; summary: string; payload: Record<string, unknown> }
export interface TestDef { id: string; group: string; name: string; measures: string; minutes: number; source: string; latest: TestResult | null }
export interface TestHistory { tests: TestDef[]; recent: TestResult[] }
export interface Suggestion { id: string; area: Area; priority: number; title: string; why: string; steps: string[]; goal: string | null; sources: string[]; accepted: boolean }
export interface Suggestions { mode: 'rules' | 'ai'; provider: string; day: number; items: Suggestion[] }
