// Settings for this terminal: appearance, accessibility, Guided Response, demo controls.
// Personal settings (photo, PIN) live in My space.
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { Prefs } from '../state/prefs'
import { useSession } from '../state/session'

function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return <button className={`switch ${on ? 'on' : ''}`} role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)} />
}

function Row({ title, desc, children }: { title: string; desc: string; children: React.ReactNode }) {
  return (
    <div className="set-row">
      <div className="grow"><b>{title}</b><p className="small muted">{desc}</p></div>
      {children}
    </div>
  )
}

export default function Settings() {
  const { prefs, setPref, setStep, toast } = useSession()
  const nav = useNavigate()
  const toggle = (k: keyof Prefs, title: string, desc: string) => (
    <Row title={title} desc={desc}><Switch on={prefs[k] as boolean} onChange={v => setPref(k, v as never)} label={title} /></Row>
  )
  return (
    <div className="page settings">
      <div className="head rise"><div><h1>Settings</h1><p className="sub">For this terminal. Your photo and PIN are in My space.</p></div></div>

      <section className="set-group rise" style={{ ['--d' as string]: 1 }}>
        <h2>Appearance</h2>
        <Row title="Theme" desc="Dark suits a dim cabin; light suits a bright room. The 3D body and Guided Response stay dark.">
          <div className="seg-ctl" role="radiogroup" aria-label="Theme">
            {(['dark', 'light', 'system'] as const).map(t => (
              <button key={t} role="radio" aria-checked={prefs.theme === t} className={prefs.theme === t ? 'on' : ''} onClick={() => setPref('theme', t)}>
                {t === 'system' ? 'Match device' : t[0].toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
        </Row>
      </section>

      <section className="set-group rise" style={{ ['--d' as string]: 2 }}>
        <h2>Accessibility</h2>
        {toggle('largeText', 'Larger text', 'Everything about 12% bigger, for reading at arm\'s length or with gloves.')}
        {toggle('highContrast', 'Higher contrast', 'Stronger text and lines for glare or tired eyes.')}
        {toggle('reduceMotion', 'Reduce motion', 'No entrance animations or pulsing. The device setting is followed too.')}
      </section>

      <section className="set-group rise" style={{ ['--d' as string]: 3 }}>
        <h2>Guided Response</h2>
        {toggle('voice', 'Read steps aloud', 'Start every emergency with the voice on, so hands stay free.')}
      </section>

      <section className="set-group rise" style={{ ['--d' as string]: 4 }}>
        <h2>Demo</h2>
        {toggle('storyBar', 'Show the demo story bar', 'The bar at the bottom that walks through the six scenes.')}
        <Row title="Replay the intro" desc="The canary story and the mission, from the start.">
          <button className="btn" onClick={() => nav('/welcome')}>Replay</button>
        </Row>
        <Row title="Reset the demo" desc="Clears check-ins, goals ticked, messages, emergencies, photos and changed PINs.">
          <button className="btn" onClick={async () => { await api.reset(); await setStep(0); toast('Demo reset.') }}>Reset</button>
        </Row>
      </section>
    </div>
  )
}
