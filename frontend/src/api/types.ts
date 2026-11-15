// Shapes returned by the Canary API (backend/canary/main.py). Keep in sync with the backend.
export type Level = 0 | 1 | 2
export type Area = 'physical' | 'mental'

export interface Place {
  id: string; name: string; sub: string; gravity_key: string; gravity: string
  delay_s: number; reply: string; hospital: string; dose_rate: number; what: string
  /** the planet a place belongs to (a rover uses its planet's sols and protocols) and the EVA done there */
  body?: 'earth' | 'space' | 'moon' | 'mars'; eva?: 'none' | 'microgravity' | 'surface'
}
/** A NASA-STD-3001 Volume 1 check of one indicator (domain/standards.py). */
export interface Standard {
  level: Level; status: 'in' | 'near' | 'limit'; text: string; item: string; source: string; url: string; verified: boolean
}
export interface StandardsSummary {
  document: { id: string; name: string; url: string; checked: string }
  checked: Record<string, { items: string[]; text: string; verified: boolean } & Record<string, unknown>>
  not_checked: { items: string[]; why: string }[]
}
export interface StoryStep { loc: string; day: number; me: string; storm: string | null; when: string; text: string }
export interface Leg { location: string; start: number; end: number; label: string }
export interface LegNow extends Leg { index: number; day_in_leg: number; length: number; next: Leg | null; days_to_next: number | null }
export interface Plan { name: string; legs: Leg[]; preset: string | null; presets: Record<string, string> }
export interface Clock { mode: 'simulated' | 'real'; date: string; time: string }
export interface Mission {
  step: number; steps: number; story: StoryStep | null; day: number; day_label: string
  location: string; place: Place; storm: string | null; suggested_user: string; learning: boolean
  leg: LegNow; custom_day: boolean; location_override: boolean; plan_name: string; setup_done: boolean
  callsign: string | null; registered: boolean; clock: Clock
}
/** One bookmark of the demo story (GET /api/scenes): a day, a place, a person, a sentence. */
export interface Scene { index: number; day: number; location: string; person: string; storm: string | null; when: string; text: string }
export interface CrewInfo { id: string; name: string; role: string; initials: string; home: string; age: number }
export interface IndicatorDef { name: string; unit: string; area: Area; facet?: string; dir: string; sd: number; dp: number; max_age?: number }
export interface SystemDef { name: string; area: Area; indicators: string[]; space: string; hazard: string }
export interface Source { id: string; name: string; org: string; url: string; used_for: string }
export interface Catalog {
  locations: Record<string, Omit<Place, 'id'>>; indicators: Record<string, IndicatorDef>
  systems: Record<string, SystemDef>; region_system: Record<string, string>
  crew: CrewInfo[]; story: StoryStep[]; sources: Source[]; standards?: StandardsSummary
  /** "How to measure and why" per indicator id (and radiation), English, each text with its source or none */
  guide?: Record<string, GuideEntry>
}
export interface GuideEntry {
  how: string; effect: string; actions: { green: string; amber: string; red: string }; frequency: string
  sources: { how: string | null; effect: string | null; actions: string[] }
}
export interface Indicator {
  id: string; name: string; unit: string; area: Area; facet?: string; dp: number
  /** null when nothing current is known (status "no_data"): never measured, or the last reading is older than the indicator allows */
  value: number | null; baseline: number | null; delta: number | null; z: number | null; bad: number | null; level: Level; source: string
  status?: 'no_data'
  origin: 'user' | 'simulated' | 'real' | 'none'; last_measured_day: number | null; age_days: number | null; stale?: boolean
  /** no normal of their own yet: only the population range and the NASA standard speak */
  learning?: boolean; baseline_need?: number | null
  /** last day of the care window that tightens this person's thresholds */
  sensitive_until?: number
  spread: number; baseline_from: 'preflight' | 'early_flight' | 'learning' | 'catalog'; baseline_n: number
  population: { low: number | null; high: number | null; status: 'in' | 'out' | 'critical' | 'no_data'; source: string; verified: boolean }
  /** NASA-STD-3001 limit for this indicator today, in flight only; null when the standard sets none Canary can check */
  standard?: Standard | null
}
export interface SystemState { id: string; name: string; area: Area; level: Level; status: string; indicators: string[]; note: string | null; risks?: string[]; no_data?: boolean }
export interface AlertGoal { id: string; area: Area; title: string }
export interface Alert {
  id: string; level: Level; title: string; why: string; todo: string[]; sys?: string | null
  protocol?: string; test?: string; env?: boolean; data?: boolean; risk?: string | null
  /** hazards (R I D G E) that are possible factors here, from the team's matrix; never a cause */
  hazards?: HazardId[]; hazard_note?: string
  since_day?: number; days_active?: number; seen?: boolean; sources: string[]; goals: AlertGoal[]
}
export type HazardId = 'R' | 'I' | 'D' | 'G' | 'E'
export interface HazardLink { hazard: HazardId; key: string; why: string; source: string; verified: boolean }
export interface RiskEvidence {
  indicator?: string; checkin?: string; key?: string; text: string; value: number | null; baseline: number | null; z: number | null
  origin: 'user' | 'simulated' | 'real'; source: string; points: number; drift?: { slope: number; days_to_limit: number }
  /** exams: how old the last one is, and whether it is overdue (shown, never counted as a health signal) */
  age_days?: number; stale?: boolean; due_every_days?: number; baseline_outside?: boolean
}
export interface Risk {
  id: string; name: string; nasa_red: boolean; systems: string[]; clock_days: number; level: Level; score: number
  trend: 'rising' | 'stable' | 'falling'; evidence: RiskEvidence[]; since_day: number | null; source: string; verified: boolean
  /** real = measured (NASA data or typed in the app), simulated = none of it, partial = a mix */
  data: 'real' | 'partial' | 'simulated' | 'none'; panel_due: boolean
  hazards: HazardId[]; hazard_links: HazardLink[]; hazard_note: string; system_levels?: Record<string, Level>
  note?: string; dose?: { now_msv: number; limit_msv: number; pct: number; cross_day: number | null; same_for_everyone: boolean; note: string }
}
/** score is null when nothing is measured in the area */
export interface AreaState { score: number | null; level: Level; status: string }
export interface Dose {
  mission_msv: number; rate_msv_day: number; career_limit_msv: number; pct_of_limit: number; simulated: boolean
  limit_source?: string
  /** measured = every day from a dosimeter, estimated = none, partial = a mix */
  origin?: 'measured' | 'partial' | 'estimated'; measured_days?: number; estimated_days?: number
  /** for one crew member: dose from earlier flights (record or estimate) and the career total NASA's limit counts */
  prior_msv?: number; prior_estimate?: boolean; prior_source?: string; career_msv?: number; career_pct_of_limit?: number
}
export interface Goal {
  id: string; area: Area; title: string; why: string; sys?: string | null
  action?: string | null; by: 'routine' | 'alert' | 'medical' | 'suggestion'; done: boolean
  verify?: { indicator: string; after_days: number }
  advice?: { status: AdviceStatus; check_day: number }
  adjusted?: { pct: number; minutes: number; target: number; reason: 'fatigue'; max_pct: number }
}
export type AdviceStatus = 'pending' | 'improved' | 'same' | 'worse' | 'no_data'
export interface AdviceItem {
  goal_id: string; origin: 'alert' | 'suggestion'; indicator: string; risk: string | null
  start_day: number; check_day: number; start_bad: number; status: AdviceStatus; bad_at_check?: number | null
}
export interface AdviceResponse {
  day: number; active: AdviceItem[]; done: AdviceItem[]; margin: number
  escalation: { risk: string; key: string; alternative: { id: string; title: string } }[]
}
export interface Badge { id: string; name: string; desc: string; area: string; progress: number; need: number; earned: boolean }
export interface Profile {
  crew_id: string; goals_week: number; goals_week_by_area: Record<Area, number>; streak: number; completion_7d: number
  badges: Badge[]; badges_earned: number; daily_done: [number, number, number][]; rank?: number
  name?: string; initials?: string; role?: string
}
export interface TeamGoal {
  id: string; area: Area; title: string; target: number; unit: string
  value: number; pct: number; done: boolean
  /** one sentence: what the mission is */
  what: string
  /** the routine personal goals that count toward it (catalog data, the same for everyone) */
  personal_ids: string[]
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
/** range is the laboratory's for the person's sex; null for C-reactive protein, whose panel gives none */
export interface Analyte {
  unit: string; range: { min: number; max: number } | null; values: (number | null)[]; status: ('in' | 'out' | null)[]
  panel?: 'cbc' | 'cmp'; source?: string
}
/** Lab results registered for the person; with none, `analytes` is empty and `origin` is null. */
export interface Blood { subject: string | null; timepoints: string[]; lymphocytes: number[]; range: { min: number; max: number } | null; unit: string; note: string; analytes: Record<string, Analyte>; origin: 'real' | null }
export interface CrewDetail {
  crew: CrewInfo; mission: Mission; indicators: Record<string, Indicator>; systems: Record<string, SystemState>
  alerts: Alert[]; risks: Risk[]; areas: Record<Area, AreaState>; level: Level; status: string; dose: Dose
  /** [day, value]; a day without a current measurement has null: the chart leaves a gap */
  trends: Record<string, [number, number | null][]>; no_data?: boolean; goals: Goal[]; profile: Profile; blood: Blood
  standard_profile?: { eva: 'none' | 'microgravity' | 'surface'; prior_dose: { msv: number; estimate: boolean; source: string }; sex: string }
  events: { id: number; kind: string; day: number; payload: Record<string, unknown>; has_photo: boolean }[]
  system_info: Record<string, { space: string; hazard: string }>
  ops: Ops; care_by: string; access: 'self' | 'medical'; care_events: CareEvent[]
}
export interface CareEvent {
  emergency_id: number; protocol: string; name: string; outcome: string; day: number; until_day: number
  ops: 'full' | 'limited' | 'rest'; origin: 'user'; source: string
}
export interface Ops {
  key: 'full' | 'limited' | 'rest'; label: string; level: Level
  /** inside the care window of a closed emergency: why, and the last restricted day */
  reason?: string; until_day?: number; care?: { protocol: string; name: string; ops: 'full' | 'limited' | 'rest'; day: number; until_day: number }
}
export interface Notice { crew_id: string; name: string; alert_id: string; title: string; since_day: number; day: number; level: Level; to: string; to_name: string }
export interface Person {
  id: string; name: string; role: string; initials: string; home: string
  today: { done: number; total: number; streak: number }
}
export interface Hazard { title: string; level: Level; what: string; sources: string[] }
export interface Ridge { id: HazardId; name: string; what: string; level: Level; label: string; here: string; systems: string[]; system_names: string[]; basis?: string; assumption?: boolean }
export interface Warning { id: string; level: Level; title: string; why: string; todo: string[]; sources: string[]; protocol?: string | null }
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
/** One person in the crew's ranking: routine goals only and the patches earned, never the split by area, daily counts or patch progress. */
export interface LeaderRow {
  crew_id: string; goals_week: number; completion_7d: number; streak: number; badges_earned: number
  /** earned patches: effort-based, public */
  patches: { id: string; name: string }[]
  rank: number; name: string; initials: string; role: string
}
export interface Leaderboard { rows: LeaderRow[];team: TeamGoal[]; crew_goals_week: number; team_done: number; team_total: number }
export interface Step { i: number; t?: string; q?: string; yes?: number | string; no?: number | string; timer?: number; metro?: number; breath?: number; end?: number; variant?: string | null }
export interface Protocol { id: string; name: string; sign: string; kit: string[]; after: string[]; after_items: { title: string; days: number }[]; window_days: number; ops: 'full' | 'limited' | 'rest'; steps: Step[]; source: string }
export interface Protocols { order: string[]; protocols: Record<string, Protocol>; reviewed: boolean; care_note?: { source: string; verified: boolean; note: string } }
export interface ProtocolPage {
  id: string; kind: 'emergency' | 'operational'; name: string; sign: string | null; audience: string; guided: boolean
  when: string[]; steps: { t: string | null; variant: string | null; q: string | null }[]; watch: string[]; kit: string[]
  window_days: number; ops: 'full' | 'limited' | 'rest' | null; links: string[]; source: string | null; live: string[]
  standard: { text: string; items: string[]; name: string; url: string; checked: string } | null
}
export interface InForce { id: string; level: Level; reason: string; audience?: string }
export interface ProtocolLibrary {
  in_force: InForce[]; emergency: ProtocolPage[]; operational: ProtocolPage[]; reviewed: boolean; note: string
  care_table: { id: string; name: string; window_days: number; ops: 'full' | 'limited' | 'rest' }[]; place: { id: string; name: string }
}
export interface ProtocolMatch {
  mode: 'rules' | 'ai'; provider: string
  matches: { id: string; name: string; sign: string; score: number; matched: string[] }[]
  fallback: { id: string; name: string; sign: string } | null
}
export interface Emergency { id: number; protocol: string | null; patient: string | null; responder: string | null; location: string; day: number; started_at: number; ended_at: number | null; outcome: string | null; log: [number, string][] }
export interface Message { id: number; sender: string; recipient: string; kind: string; text: string; sent_at: number; deliver_at: number; delivered: boolean; eta_s: number }
export interface Claim { text: string; source_ids: string[] }
export interface AssistantAnswer {
  id: number; mode: 'ai' | 'grounded' | 'refused' | 'emergency' | 'unknown'; provider: string; provider_error?: string | null
  answer: string; claims: Claim[]; sources: string[]; tools_used: { tool: string; args: Record<string, string> }[]; dropped: number
  question?: string
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
  notices: Notice[]; care_sensitivity: { factor: number; source: string; verified: boolean }
  crew: {
    id: string; name: string; role: string; level: Level; ops: Ops; care_events: CareEvent[]; areas: Record<Area, AreaState>; indicators: Record<string, Indicator>; systems: Record<string, SystemState>; alerts: Alert[]
    /** the short form of each risk; evidence and hazard links are in the person view */
    risks: Pick<Risk, 'id' | 'name' | 'nasa_red' | 'level' | 'trend' | 'since_day' | 'data'>[]
    dose: Dose; standard_profile?: CrewDetail['standard_profile']
  }[]
}
export interface MedGoal { id: number; who: string; area: Area; title: string; why: string; from_day: number; to_day: number }
export interface TestResult { id: number; kind: string; day: number; at: number; summary: string; payload: Record<string, unknown>
  /** vitals only: a photo of the display is kept with it (the person and the medical team can open it) */
  has_photo: boolean }
export interface TestDef { id: string; group: string; name: string; measures: string; minutes: number; source: string; latest: TestResult | null }
export interface CheckinResult { ok: boolean; summary: string; goal: string | null; conclusion: { population: string; personal: string; text: string } | null }
export interface TestHistory { tests: TestDef[]; recent: TestResult[] }
export interface Suggestion { id: string; area: Area; priority: number; title: string; why: string; steps: string[]; goal: string | null; sources: string[]; accepted: boolean
  /** One short line each, either may be empty: what in the environment fits this today, and what in the person's own state. */
  because_outside: string; because_inside: string; protocol: string | null
  rank: { priority: number; both: number; learned: number; score: number; accepted: number; dismissed: number } }
export interface Suggestions { mode: 'rules' | 'ai'; provider: string; day: number; items: Suggestion[]; context: { place: string; in_force: string[] } }
export interface PersonalRecord {
  name: string; role: string; home: string; dob: string; age: number; sex: string; nationality: string; languages: string[]
  agency: string; flights: number; days_in_space: number; height_cm: number; weight_kg: number; bmi: number
  blood_type: string; skin_type: string; handedness: string; vision: string; allergies: string[]; medications: string[]
  conditions: string[]; diet: string; vaccinations: string; emergency_contact: string; date_today: string
  registered_by: string; registered_on: string
  eva: 'surface' | 'microgravity' | 'none'; prior_dose: { msv: number; estimate: boolean; source: string }
}
export interface MissionCrewInfo { id: string; name: string; role: string; initials: string; home: string; nationality?: string; agency?: string; languages?: string[]; flights?: number; days_in_space?: number }
export interface MissionOverview {
  registered: boolean; callsign: string | null; name: string; launch_date: string; today_date: string; destination: string
  flight_days: number; legs: Leg[]; mission: Mission; crew: MissionCrewInfo[]
}
export interface ControlPerson { id: string; name: string; role: string; initials: string; home: string; ops: Ops; today: { done: number; total: number; streak: number } | null; last_checkin_day: number | null }
export interface ControlOverview {
  registered: boolean; mission: Mission; overview: MissionOverview; people: ControlPerson[]; ridge: Ridge[]
  warnings: { title: string; todo: string[] }[]; dose: Dose; emergencies: Emergency[]
}
export interface SeatForm {
  /** the person's id; left out, the server gives s1 to s6 in order */
  seat?: string; name: string; role: string; home: string; pin: string; dob: string; sex: string; nationality: string; languages: string[]
  agency: string; flights: number; days_in_space: number; height_cm: number; weight_kg: number; blood_type: string; skin_type: string
  handedness: string; vision: string; allergies: string[]; medications: string[]; conditions: string[]; diet: string; vaccinations: string; emergency_contact: string
  /** EVA role (surface, microgravity, none) and the dose from earlier flights in mSv; empty means "estimated from days in space". */
  eva?: string; prior_dose_msv?: number | null
}
export interface MissionForm { callsign: string; name: string; launch_date: string; preset: string; rover?: boolean }
export interface ControlDemo {
  crew: SeatForm[]; mission: MissionForm; presets: Record<string, string>
  /** Profiles that can carry a rover leg, the station's daily dose (the prior-dose estimate) and each profile's legs. */
  rover_presets: string[]; iss_dose_msv_per_day: number
  itineraries: Record<string, { rover: Leg[]; plain: Leg[] }>
}

/** GET /api/control/data-status: counts and dates only, never a value. */
export interface DataStatus {
  ingest_configured: boolean; package: string | null
  counts: { observations: number; goal_entries: number; events: number; scenes: number }
  readings: { crew_id: string; indicator: string; last_day: number; last_received_at: string; count: number }[]
}
export interface SpaceEvent {
  id: string; kind: 'sep' | 'mars'; start_day: number; end_day: number; locations: string[]; extra_dose_msv: number
  origin: 'real' | 'simulated' | 'donki'; source: string; note: string
}
export interface NewSpaceEvent { kind: string; start_day: number; end_day: number; locations: string[]; extra_dose_msv: number; origin: string; note?: string }
/** What an import stored; `errors` is empty on success (a failed import answers 422 and writes nothing). */
export interface ImportResult {
  accepted: { mission: number; legs: number; crew: number; observations: number; space_events: number; goal_log: number; scenes: number }
  duplicates: { observations: number }
  errors: { field: string; message: string }[]
}
