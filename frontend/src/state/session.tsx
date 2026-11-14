// Shared app state: the mission clock, who is using this terminal (no accounts), and a revision
// counter that every screen watches to refetch after anything changes.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { Catalog, Mission } from '../api/types'

interface Session {
  catalog: Catalog | null
  mission: Mission | null
  me: string | null
  setMe: (id: string | null) => void
  rev: number
  bump: () => void
  setStep: (i: number) => Promise<void>
  setLocation: (loc: string | null) => Promise<void>
  emergency: boolean
  setEmergency: (v: boolean) => void
  askOpen: boolean
  setAskOpen: (v: boolean) => void
  toast: (t: string) => void
  toasts: { id: number; t: string }[]
}

const Ctx = createContext<Session | null>(null)

function load(k: string): string | null {
  try { return localStorage.getItem(k) } catch { return null }
}
function save(k: string, v: string | null) {
  try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v) } catch { /* storage blocked */ }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [mission, setMission] = useState<Mission | null>(null)
  const [me, setMeState] = useState<string | null>(load('canary.me'))
  const [rev, setRev] = useState(0)
  const [emergency, setEmergency] = useState(false)
  const [askOpen, setAskOpen] = useState(false)
  const [toasts, setToasts] = useState<{ id: number; t: string }[]>([])
  const tid = useRef(0)

  useEffect(() => { api.catalog().then(setCatalog).catch(() => undefined) }, [])
  useEffect(() => { api.mission().then(setMission).catch(() => undefined) }, [rev])

  const bump = useCallback(() => setRev(r => r + 1), [])
  const setMe = useCallback((id: string | null) => { setMeState(id); save('canary.me', id) }, [])
  const toast = useCallback((t: string) => {
    const id = ++tid.current
    setToasts(x => [...x, { id, t }])
    setTimeout(() => setToasts(x => x.filter(y => y.id !== id)), 3600)
  }, [])
  const setStep = useCallback(async (i: number) => {
    const m = await api.setStep(i)
    setMission(m)
    setMe(m.suggested_user)
    bump()
  }, [bump, setMe])
  const setLocation = useCallback(async (loc: string | null) => { setMission(await api.setLocation(loc)); bump() }, [bump])

  const value = useMemo(() => ({ catalog, mission, me, setMe, rev, bump, setStep, setLocation, emergency, setEmergency, askOpen, setAskOpen, toast, toasts }),
    [catalog, mission, me, setMe, rev, bump, setStep, setLocation, emergency, askOpen, toast, toasts])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSession(): Session {
  const s = useContext(Ctx)
  if (!s) throw new Error('useSession outside SessionProvider')
  return s
}

/** Fetch with the session revision as a dependency: any mutation anywhere refreshes every screen. */
export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const { rev } = useSession()
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    fn().then(d => { if (live) { setData(d); setError(null) } }).catch(e => { if (live) setError(String(e.message || e)) })
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rev, ...deps])
  return { data, error, setData }
}
