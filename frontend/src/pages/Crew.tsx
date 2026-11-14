import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Avatar, CountUp, Loading, Status } from '../components/ui'
import { useApi, useSession } from '../state/session'

const SYS = ['brain', 'heart', 'lungs', 'skeleton', 'muscles', 'eyes', 'kidneys', 'gut', 'immune', 'skin']

export default function Crew() {
  const { catalog } = useSession()
  const { data } = useApi(() => api.crew(), [])
  const nav = useNavigate()
  if (!data || !catalog) return <Loading what="crew" />
  const need = data.crew.filter(c => c.level)
  return (
    <div className="page">
      <div className="head rise"><div><span className="eyebrow">Crew · {data.mission.day_label}</span>
        <h1 style={{ marginTop: 6 }}>{need.length ? `${need.length} of ${data.crew.length} need attention` : 'The whole crew is on track'}</h1></div></div>

      <div className="stats">
        <div className="stat rise"><div className="k">Crew physical</div><b className="num"><CountUp value={data.crew_readiness.physical} /></b><div className="s">average of four</div></div>
        <div className="stat rise" style={{ ['--d' as string]: 1 }}><div className="k">Crew mental</div><b className="num"><CountUp value={data.crew_readiness.mental} /></b><div className="s">average of four</div></div>
        <div className="stat rise" style={{ ['--d' as string]: 2 }}><div className="k">Mission dose (simulated)</div><b className="num"><CountUp value={data.dose.mission_msv} dp={1} /><small>mSv</small></b><div className="s">{data.dose.pct_of_limit}% of the career limit</div></div>
        <div className={`stat rise s${data.space_weather.active ? 2 : 0}`} style={{ ['--d' as string]: 3 }}><div className="k">Space weather</div><b className={data.space_weather.active ? 'c' : ''}>{data.space_weather.active ? 'Storm' : 'Calm'}</b><div className="s">NASA DONKI</div></div>
      </div>

      <section className="grid g4">
        {[...data.crew].sort((a, b) => b.level - a.level).map((c, i) => (
          <button key={c.id} className="detail-card person rise" style={{ ['--d' as string]: i + 2 }} onClick={() => nav(`/crew/${c.id}`)}>
            <div className="row"><Avatar initials={c.initials} size="lg" /><div className="grow"><h3>{c.name}</h3><div className="small muted">{c.role}</div></div></div>
            <Status level={c.level}>{c.top_alert ?? 'Within personal normal'}</Status>
            <div className="dual">
              <div><span className="k">Physical</span><b>{c.areas.physical.score}</b><Status level={c.areas.physical.level} /></div>
              <div><span className="k">Mental</span><b>{c.areas.mental.score}</b><Status level={c.areas.mental.level} /></div>
            </div>
          </button>
        ))}
      </section>

      <section className="detail-card rise" style={{ ['--d' as string]: 6 }}>
        <div className="section-head"><h2>Body systems by person</h2><span className="sub">Each person against their own normal. Coloured: watch or act.</span></div>
        <div className="scroll"><table className="t">
          <thead><tr><th>Crew member</th>{SYS.map(s => <th key={s} style={{ textAlign: 'center' }}>{catalog.systems[s].name.split(/ & | /)[0]}</th>)}</tr></thead>
          <tbody>{data.crew.map(c => (
            <tr key={c.id} className="click" onClick={() => nav(`/crew/${c.id}`)}>
              <td><div className="row"><Avatar initials={c.initials} /><span>{c.name}</span></div></td>
              {SYS.map(s => <td key={s} style={{ textAlign: 'center' }}><span className={`sq s${c.systems[s]}`} title={`${catalog.systems[s].name}: ${['On track', 'Watch', 'Act'][c.systems[s]]}`} /></td>)}
            </tr>))}</tbody>
        </table></div>
      </section>
    </div>
  )
}
