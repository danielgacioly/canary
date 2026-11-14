// Your space: the only place your own numbers, alerts and advice appear on a crew terminal.
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import BodyView from '../components/BodyView'
import { EnterGate } from '../components/People'
import PinPad, { PinModal } from '../components/PinPad'
import { Icon, Loading } from '../components/ui'
import Check, { type CheckKind } from '../features/Checks'
import { useApi, useSession } from '../state/session'

export default function Me() {
  const { me } = useSession()
  const [params] = useSearchParams()
  const who = params.get('who')  // the demo bar's "Enter as ..." lands here: still asks for that person's PIN
  if (!me || (who && who !== me)) return <EnterGate preselect={who} />
  return <MySpace me={me} />
}

function MySpace({ me }: { me: string }) {
  const { setMe, bump, toast } = useSession()
  const nav = useNavigate()
  const { data: d, error } = useApi(() => api.crewDetail(me), [me])
  const [check, setCheck] = useState<CheckKind | null>(null)
  const [pinOpen, setPinOpen] = useState(false)
  if (error) return <div className="page"><p className="muted">Cannot reach the Canary API. Is the backend running on port 8000?</p></div>
  if (!d) return <Loading what="your health" />
  const share = async () => {
    await api.setSharing(me, !d.shared)
    toast(d.shared ? 'Your health is private again.' : 'The crew can now see your data and history. Alerts and advice stay private.')
    bump()
  }
  return (
    <div className="page" style={{ gap: 32 }}>
      <div className="privacy-bar rise">
        <Icon name="lock" />
        <span className="grow"><b>Your private space.</b> <span className="muted">Only you and the medical team see this. The crew sees only your goal participation. Your alerts go to {d.care_by}.</span>
          {d.ops && <span className="small dim" style={{ display: 'block', marginTop: 2 }}>Medical status: <span className={`s${d.ops.level} c`} style={{ fontWeight: 600 }}>{d.ops.label}</span> (visible to you and the medical team)</span>}</span>
        <button className="row small" onClick={share} aria-pressed={d.shared}>
          <span className={`switch ${d.shared ? 'on' : ''}`} />Share data with the crew
        </button>
        <button className="btn sm ghost" onClick={() => setPinOpen(true)}><Icon name="shield" />Change PIN</button>
        <button className="btn sm ghost" onClick={() => { setMe(null); nav('/crew') }}><Icon name="lock" />Lock</button>
      </div>
      <BodyView d={d} onCheck={setCheck} />
      {check && <Check kind={check} onClose={() => setCheck(null)} />}
      {pinOpen && <ChangePin me={me} first={d.crew.name.split(' ')[0]} onClose={() => setPinOpen(false)} onDone={() => { setPinOpen(false); toast('PIN changed. Use the new one next time.') }} />}
    </div>
  )
}

/** Three pads in a row: the current PIN (checked by the server), a new one, the new one again. */
function ChangePin({ me, first, onClose, onDone }: { me: string; first: string; onClose: () => void; onDone: () => void }) {
  const [step, setStep] = useState<'current' | 'new' | 'confirm'>('current')
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [mismatch, setMismatch] = useState(false)
  const stepNo = { current: 1, new: 2, confirm: 3 }[step]
  return (
    <PinModal onCancel={onClose}>
      <span className="eyebrow" style={{ display: 'block', textAlign: 'center', marginBottom: 8 }}>Change PIN · step {stepNo} of 3</span>
      {step === 'current' && <PinPad key="c" title="Current PIN" subtitle={`${first}, enter the PIN you use now`} onCancel={onClose}
        onSubmit={async pin => { await api.crewSignIn(me, pin); setCurrent(pin); setStep('new') }} />}
      {step === 'new' && <PinPad key="n" title="New PIN" subtitle={mismatch ? 'The two did not match. Choose again.' : 'Choose 4 digits you will remember'} onCancel={onClose}
        onSubmit={async pin => { if (pin === current) throw new Error('Pick a different PIN from the current one.'); setNext(pin); setMismatch(false); setStep('confirm') }} />}
      {step === 'confirm' && <PinPad key="m" title="Confirm new PIN" subtitle="Enter the new PIN once more" onCancel={onClose}
        onSubmit={async pin => {
          if (pin !== next) { setMismatch(true); setStep('new'); return }
          await api.changePin(me, current, pin)
          onDone()
        }} />}
    </PinModal>
  )
}
