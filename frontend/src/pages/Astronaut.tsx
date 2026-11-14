import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import BodyView from '../components/BodyView'
import { Avatar, Icon, Loading, Patch, Spark, Status } from '../components/ui'
import { useApi, useSession } from '../state/session'

export default function Astronaut() {
  const { id = '' } = useParams()
  const { me } = useSession()
  const { data: d } = useApi(() => api.crewDetail(id), [id])
  if (!d) return <Loading what="crew member" />
  const p = d.profile
  return (
    <div className="page">
      <Link to="/crew" className="back"><Icon name="back" />Crew</Link>
      <div className="head rise">
        <Avatar initials={d.crew.initials} size="xl" />
        <div><h1>{d.crew.name}</h1><p className="sub">{d.crew.role} · {d.crew.home} · level {p.level} · {p.xp_week} XP this week · {p.badges_earned} patches</p></div>
        <div className="right"><Status level={d.level}>{d.status}</Status></div>
      </div>
      <BodyView key={d.crew.id} d={d} self={d.crew.id === me} />
      <section className="detail-card rise" style={{ padding: 8 }}>
        <div className="section-head" style={{ padding: '12px 12px 0' }}><h2>All numbers</h2><span className="sub">last 30 days against their own normal</span></div>
        <div className="scroll"><table className="t">
          <thead><tr><th>Indicator</th><th>Now</th><th>Their normal</th><th>Last 30 days</th><th>Status</th></tr></thead>
          <tbody>{Object.values(d.indicators).map(i => (
            <tr key={i.id}>
              <td><b>{i.name}</b><div className="small dim">{i.area}</div></td>
              <td className="num">{i.value.toFixed(i.dp)} <span className="dim">{i.unit}</span></td>
              <td className="num muted">{i.baseline.toFixed(i.dp)}</td>
              <td><Spark data={d.trends[i.id]} base={i.baseline} color={i.area === 'mental' ? 'var(--mental)' : 'var(--physical)'} w={120} h={28} /></td>
              <td><Status level={i.level} /></td>
            </tr>))}</tbody>
        </table></div>
      </section>
      <section>
        <div className="section-head"><h2>Patches</h2></div>
        <div className="patches">{p.badges.map(b => (
          <div key={b.id} className={`patch ${b.earned ? '' : 'off'}`}><Patch id={b.id} earned={b.earned} /><b>{b.name}</b><span className="small muted">{b.desc}</span></div>))}</div>
      </section>
    </div>
  )
}
