import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Avatar, Loading, Status, Tabs } from '../components/ui'
import { useApi, useSession } from '../state/session'

const SYS = ['brain', 'heart', 'lungs', 'skeleton', 'muscles', 'eyes', 'kidneys', 'gut', 'immune', 'skin']

export default function Crew() {
  const { catalog } = useSession()
  const { data } = useApi(() => api.crew(), [])
  const [tab, setTab] = useState<'people' | 'systems'>('people')
  const nav = useNavigate()
  if (!data || !catalog) return <Loading what="crew" />
  const need = data.crew.filter(c => c.level)
  return (
    <div className="page">
      <div className="head">
        <div><h1>{need.length ? `${need.length} of ${data.crew.length} need attention` : 'The whole crew is on track'}</h1>
          <p className="sub">Crew average: physical {data.crew_readiness.physical}, mental {data.crew_readiness.mental} · mission dose {data.dose.mission_msv} mSv (simulated) · space weather {data.space_weather.headline.toLowerCase()}</p></div>
      </div>
      <Tabs value={tab} onChange={setTab} options={[['people', 'People'], ['systems', 'Body systems']]} />

      {tab === 'people' && (
        <div className="grid g4">
          {[...data.crew].sort((a, b) => b.level - a.level).map(c => (
            <button key={c.id} className="card person" onClick={() => nav(`/crew/${c.id}`)}>
              <div className="row"><Avatar initials={c.initials} size="lg" /><div className="grow"><h3>{c.name}</h3><div className="small muted">{c.role}</div></div></div>
              <Status level={c.level}>{c.top_alert ?? 'Within personal normal'}</Status>
              <div className="dual">
                <div><span className="k">Physical</span><b>{c.areas.physical.score}</b><Status level={c.areas.physical.level} /></div>
                <div><span className="k">Mental</span><b>{c.areas.mental.score}</b><Status level={c.areas.mental.level} /></div>
              </div>
            </button>
          ))}
        </div>
      )}

      {tab === 'systems' && (
        <div className="card" style={{ padding: 8 }}>
          <div className="scroll"><table className="t">
            <thead><tr><th>Crew member</th>{SYS.map(s => <th key={s} style={{ textAlign: 'center' }}>{catalog.systems[s].name.split(/ & | /)[0]}</th>)}</tr></thead>
            <tbody>{data.crew.map(c => (
              <tr key={c.id} className="click" onClick={() => nav(`/crew/${c.id}`)}>
                <td><div className="row"><Avatar initials={c.initials} /><span>{c.name}</span></div></td>
                {SYS.map(s => <td key={s} style={{ textAlign: 'center' }}><span className={`sq s${c.systems[s]}`} title={`${catalog.systems[s].name}: ${['On track', 'Watch', 'Act'][c.systems[s]]}`} /></td>)}
              </tr>))}</tbody>
          </table></div>
          <p className="small dim" style={{ padding: '8px 12px' }}>Each square compares that person with their own normal. Coloured: watch or act.</p>
        </div>
      )}
    </div>
  )
}
