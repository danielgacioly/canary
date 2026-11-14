import { useState } from 'react'
import { api } from '../api/client'
import BodyView from '../components/BodyView'
import { Loading } from '../components/ui'
import Check, { type CheckKind } from '../features/Checks'
import { useApi, useSession } from '../state/session'

export default function Me() {
  const { me } = useSession()
  const { data: d, error } = useApi(() => (me ? api.crewDetail(me) : Promise.reject(new Error('no user'))), [me])
  const [check, setCheck] = useState<CheckKind | null>(null)
  if (error) return <div className="page"><p className="muted">Cannot reach the Canary API. Is the backend running on port 8000?</p></div>
  if (!d) return <Loading what="your health" />
  return (
    <div className="page" style={{ gap: 40 }}>
      <BodyView d={d} onCheck={setCheck} />
      {check && <Check kind={check} onClose={() => setCheck(null)} />}
    </div>
  )
}
