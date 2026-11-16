import { useSyncExternalStore } from 'react'
// The guided tour that follows the intro: which stage it is at, kept per tab (sessionStorage) so a reload keeps it and a
// new visit starts clean. Stages: control (Control sign-in), connect (registration), dashboard (Control dashboard),
// board (on board), done.
export type TourStage = 'control' | 'connect' | 'dashboard' | 'board' | 'done'
const KEY = 'canary.tour'
const EVENT = 'canary-tour'

export function tourStage(): TourStage | null {
  try { return (sessionStorage.getItem(KEY) as TourStage | null) } catch { return null }
}

export function startTour(stage: TourStage) { setTourStage(stage) }

export function setTourStage(stage: TourStage | null) {
  try {
    if (stage) sessionStorage.setItem(KEY, stage)
    else sessionStorage.removeItem(KEY)
  } catch { /* storage blocked */ }
  window.dispatchEvent(new Event(EVENT))
}

export function onTourChange(fn: () => void): () => void {
  window.addEventListener(EVENT, fn)
  return () => window.removeEventListener(EVENT, fn)
}

/** The current stage as React state: screens re-render when the tour moves. */
export function useTourStage(): TourStage | null {
  return useSyncExternalStore(onTourChange, tourStage, () => null)
}
