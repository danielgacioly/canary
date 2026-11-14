// Your space: the only place your own numbers, alerts and advice appear on a crew terminal.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import BodyView from '../components/BodyView'
import { EnterGate } from '../components/People'
import { Icon, Loading } from '../components/ui'
import Check, { type CheckKind } from '../features/Checks'
import { useApi, useSession } from '../state/session'

export default function Me() {
  const { me } = useSession()
  if (!me) return <EnterGate />
  return <MySpace me={me} />
}

function MySpace({ me }: { me: string }) {
  const { setMe, bump, toast } = useSession()
  const nav = useNavigate()
  const { data: d, error } = useApi(() => api.crewDetail(me), [me])
  const [check, setCheck] = useState<CheckKind | null>(null)
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
        <span className="grow"><b>Your private space.</b> <span className="muted">Only you and the medical team see this. The crew sees: <b style={{ color: 'var(--ink)' }}>{d.ops.label}</b>. Your alerts go to {d.care_by}.</span></span>
        <button className="row small" onClick={share} aria-pressed={d.shared}>
          <span className={`switch ${d.shared ? 'on' : ''}`} />Share data with the crew
        </button>
        <button className="btn sm ghost" onClick={() => { setMe(null); nav('/crew') }}><Icon name="lock" />Lock</button>
      </div>
      <BodyView d={d} onCheck={setCheck} />
      {check && <Check kind={check} onClose={() => setCheck(null)} />}
    </div>
  )
}
