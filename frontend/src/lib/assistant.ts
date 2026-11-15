// The assistant's status as one line of copy, read from what the backend sends (never "once connected").
import type { AssistantStatus } from '../api/types'

export const NO_MODEL = 'No model connected: answers come from rules'

/** "Assistant · gemini / gemini-3.1-flash-lite" when a model is configured, NO_MODEL otherwise; "…" until the status arrives. */
export function modelLine(st: AssistantStatus | null | undefined): string {
  if (!st) return '…'
  if (!st.configured) return NO_MODEL
  return `Assistant · ${st.provider}${st.model ? ` / ${st.model}` : ''}`
}
