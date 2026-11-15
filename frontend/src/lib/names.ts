// Names for the ids the API stores (protocol ids, crew ids, place ids, message kinds), so no raw id reaches the screen.
import { api } from '../api/client'
import { useApi, useSession } from '../state/session'

/** Protocol id → its name ("cpr" → "Not responding, not breathing"). No id: the protocol was never picked. */
export function useProtocolName(): (id: string | null | undefined) => string {
  const { data } = useApi(() => api.protocols(), [])
  return id => (id ? data?.protocols[id]?.name ?? id : 'Not identified yet')
}

const PARTY: Record<string, string> = { earth: 'Earth', canary: 'Canary', crew: 'Whole crew', 'mission-control': 'Mission Control' }

/** Who sent or received a message: a crew member's name, Earth, Canary or the free text the sender typed. */
export function usePartyName(): (who: string) => string {
  const { catalog } = useSession()
  return who => catalog?.crew.find(c => c.id === who)?.name ?? PARTY[who] ?? who
}

/** What kind of message it is, in words. A plain message has no label. */
export const MESSAGE_KIND: Record<string, string> = {
  briefing: 'Weekly briefing', alert: 'Critical alert', alert_earth: 'Report to Earth', emergency: 'Emergency report', advice: 'Advice check',
}

/** Place id → its name ("transit" → "Transit to Mars"). */
export function usePlaceName(): (id: string) => string {
  const { catalog } = useSession()
  return id => catalog?.locations[id]?.name ?? id
}
