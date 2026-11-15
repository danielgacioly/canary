// The guided tour: small flat balloons anchored to elements marked data-tour="...". The stage lives in lib/tour.ts (sessionStorage).
// A balloon shows for the first step, from the current one on, whose anchor is on the screen; Next moves past it.
import { useEffect, useState } from 'react'
import { setTourStage, useTourStage, type TourStage } from '../lib/tour'

interface Step { anchor: string; text: string; last?: boolean; noNext?: boolean }

const STEPS: Partial<Record<TourStage, Step[]>> = {
  control: [{ anchor: 'gate', text: 'Mission Control signs in here. Demo account: Sam Okoye, PIN 4242.', noNext: true }],
  connect: [
    { anchor: 'crew-demo', text: 'Use the demo crew for the people.' },
    { anchor: 'scan', text: 'No devices in this demo: use the demo devices.' },
    { anchor: 'sources', text: 'Load the demo mission.' },
    { anchor: 'save', text: 'Send it to Canary.', noNext: true },
  ],
  dashboard: [
    { anchor: 'ctl-crew', text: 'Earth sees operational status only, never health values.' },
    { anchor: 'ctl-hazards', text: 'The hazards at the crew\'s place today.' },
    { anchor: 'ctl-alerts', text: 'Open alerts: who, which alert, and whether the ship acknowledged it.' },
    { anchor: 'enter', text: 'Now see Canary the way the crew does.', noNext: true },
  ],
  board: [
    { anchor: 'crew-home', text: 'This is Canary on board: what the astronauts see.' },
    { anchor: 'crew-dots', text: 'The crew. Tap a dot to open that person.' },
    { anchor: 'hazards', text: 'Hazards here today.' },
    { anchor: 'my-space', text: 'My space: each astronaut\'s own body, goals and alerts, behind their PIN.' },
    { anchor: 'sos', text: 'Guided Response: hold for one second in an emergency.' },
    { anchor: 'story', text: 'Walk through the mission\'s key moments. Turn this bar off in Settings › Demo.', last: true },
  ],
}

const find = (a: string) => {
  const els = Array.from(document.querySelectorAll<HTMLElement>(`[data-tour="${a}"]`))
  return els.find(e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden') ?? null
}

export default function Tour() {
  const stage = useTourStage()
  const [idx, setIdx] = useState(0)
  const [box, setBox] = useState<{ i: number; r: DOMRect } | null>(null)
  useEffect(() => { setIdx(0); setBox(null) }, [stage])
  const steps = stage ? STEPS[stage] : undefined

  useEffect(() => {
    if (!steps) return
    let on: HTMLElement | null = null
    const tick = () => {
      let hit: { i: number; el: HTMLElement } | null = null
      for (let i = idx; i < steps.length && !hit; i++) { const el = find(steps[i].anchor); if (el) hit = { i, el } }
      if (on && on !== hit?.el) on.classList.remove('tour-on')
      on = hit?.el ?? null
      if (hit) { hit.el.classList.add('tour-on'); setBox(b => { const r = hit!.el.getBoundingClientRect(); return b && b.i === hit!.i && b.r.top === r.top && b.r.left === r.left && b.r.width === r.width ? b : { i: hit!.i, r } }) }
      else setBox(null)
    }
    tick()
    const t = setInterval(tick, 250)
    window.addEventListener('resize', tick); window.addEventListener('scroll', tick, true)
    return () => { clearInterval(t); window.removeEventListener('resize', tick); window.removeEventListener('scroll', tick, true); on?.classList.remove('tour-on') }
  }, [steps, idx])

  if (!steps || !box) return null
  const step = steps[box.i]
  const W = Math.min(300, window.innerWidth - 24), H = 120
  const below = box.r.bottom + 10 + H < window.innerHeight
  const above = box.r.top - 10 - H >= 0
  const inside = !below && !above  // a big anchor: sit inside it, near its top
  const top = below ? box.r.bottom + 10 : inside ? Math.max(8, Math.min(box.r.top, window.innerHeight - H - 8) + 8) : 0
  const left = Math.min(Math.max(12, box.r.left), window.innerWidth - W - 12)
  const end = () => setTourStage(null)
  return (
    <div className="tour" role="dialog" aria-label="Guided tour" style={{ top, left, width: W, ...(below || inside ? {} : { top: 'auto', bottom: window.innerHeight - box.r.top + 10 }) }}>
      <p>{step.text}</p>
      <div className="row" style={{ gap: 8 }}>
        {!step.last && <button className="btn sm ghost" onClick={end}>End tour</button>}
        <span className="grow" />
        {step.last ? <button className="btn sm pri" onClick={end}>End tour</button> : !step.noNext && <button className="btn sm pri" onClick={() => setIdx(box.i + 1)}>Next</button>}
      </div>
    </div>
  )
}
