// Settings for this terminal: appearance, accessibility, Guided Response, demo controls.
// Personal settings (photo, PIN) live in My space.
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { Prefs } from '../state/prefs'
import type { PublicAccounts } from '../api/types'
import { ActionError } from '../components/Field'
import PinPad, { PinModal } from '../components/PinPad'
import { useAction } from '../lib/useAction'
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
  const { prefs, setPref, setStep, toast, catalog } = useSession()
  const demo = catalog?.mode === 'demo'
  const [mcc, setMcc] = useState<PublicAccounts['ground']>([])
  const [mccId, setMccId] = useState<string | null>(null)
  useEffect(() => { if (demo) api.accountsPublic().then(a => setMcc(a.ground.filter(g => g.role === 'mcc'))).catch(() => undefined) }, [demo])
  const nav = useNavigate()
  const reset = useAction()
  const [askPin, setAskPin] = useState(false)
  // The reset wipes the database, so the API asks for the Canary Control sign-in. A session opened here only for the
  // reset is closed right after it; one that was already open (Canary Control on this terminal) stays.
  const doReset = (signOutAfter: boolean) => reset.run(async () => {
    try { await api.reset() } finally { if (signOutAfter) api.controlSignOut() }
    await setStep(0)
    toast('Demo reset.')
  })
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

      {demo && <section className="set-group rise" style={{ ['--d' as string]: 4 }}>
        <h2>Demo</h2>
        {toggle('storyBar', 'Show the demo story bar', 'The bar at the bottom that walks through the six scenes.')}
        <Row title="Replay the intro" desc="The canary story and the mission, from the start.">
          <button className="btn" onClick={() => nav('/welcome')}>Replay</button>
        </Row>
        <Row title="Reset the demo" desc="Clears check-ins, goals ticked, messages, emergencies, photos and changed PINs. Asks for the MCC PIN.">
          <button className="btn" disabled={reset.busy} onClick={() => api.isControl() ? doReset(false) : (setMccId(mcc[0]?.id ?? null), setAskPin(true))}>{reset.busy ? 'Resetting…' : 'Reset'}</button>
        </Row>
        <ActionError error={reset.error} />
        {askPin && (
          <PinModal onCancel={() => setAskPin(false)}>
            <>
              {mcc.length > 1 && <select aria-label="MCC account" value={mccId ?? ''} onChange={e => setMccId(e.target.value)}>{mcc.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}</select>}
              <PinPad title="MCC PIN" subtitle={`Resetting clears the whole demo${mcc.find(g => g.id === mccId) ? ` · ${mcc.find(g => g.id === mccId)!.name}` : ''}`} hint="Demo PIN: 4242" onCancel={() => setAskPin(false)}
                onSubmit={async pin => { if (!mccId) throw new Error('No MCC account is registered.'); await api.controlSignIn(pin, mccId); setAskPin(false); doReset(true) }} />
            </>
          </PinModal>
        )}
      </section>}
    </div>
  )
}
