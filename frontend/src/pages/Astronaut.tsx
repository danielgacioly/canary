import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import HealthBody from '../components/HealthBody'
import { Avatar, Icon, Loading, Patch, Pill, Spark, STATUS } from '../components/ui'
import { useApi } from '../state/session'

export default function Astronaut() {
  const { id = '' } = useParams()
  const { data: d } = useApi(() => api.crewDetail(id), [id])
  if (!d) return <Loading what="crew member" />
  const p = d.profile
  return (
    <div className="page">
      <Link to="/crew" className="small muted row" style={{ gap: 6 }}><Icon name="back" size={14} />Crew</Link>
      <div className="card" style={{ display: 'flex', gap: 22, alignItems: 'center', flexWrap: 'wrap' }}>
        <Avatar initials={d.crew.initials} size="xl" />
        <div className="col" style={{ gap: 6 }}>
          <span className="lbl">{d.crew.role} · {d.crew.home} · age {d.crew.age}</span>
          <h1>{d.crew.name}</h1>
          <div className="row"><Pill level={d.level}>{d.status}</Pill><span className="small muted">{d.alerts.length ? d.alerts[0].title : 'Nothing outside personal normal.'}</span></div>
        </div>
        <div className="row right" style={{ gap: 24 }}>
          <div className="kpi"><span className="lbl">Level</span><b className="num" style={{ color: 'var(--gold)' }}>{p.level}</b></div>
          <div className="kpi"><span className="lbl">XP this week</span><b className="num">{p.xp_week}</b></div>
          <div className="kpi"><span className="lbl">Goals, 7 days</span><b className="num">{p.completion_7d}<small>%</small></b></div>
          <div className="kpi"><span className="lbl">Patches</span><b className="num">{p.badges_earned}<small>/{p.badges.length}</small></b></div>
        </div>
      </div>

      <HealthBody d={d} />

      <section className="card">
        <div className="head"><h2>All indicators against personal normal</h2><span className="small muted">Last 30 days · dashed line is their baseline</span></div>
        <div className="scroll">
          <table className="t">
            <thead><tr><th>Indicator</th><th>Area</th><th>Now</th><th>Normal</th><th>Deviation</th><th>30 days</th><th>Status</th></tr></thead>
            <tbody>{Object.values(d.indicators).map(i => (
              <tr key={i.id}>
                <td><b>{i.name}</b></td>
                <td><span className={`tag ${i.area === 'mental' ? 'ment' : 'phys'}`}>{i.area}</span></td>
                <td className="num">{i.value.toFixed(i.dp)} <span className="dim">{i.unit}</span></td>
                <td className="num muted">{i.baseline.toFixed(i.dp)}</td>
                <td className="num">{i.z > 0 ? '+' : ''}{i.z.toFixed(1)} σ</td>
                <td><Spark data={d.trends[i.id]} base={i.baseline} color={i.area === 'mental' ? 'var(--mental)' : 'var(--physical)'} w={120} h={28} /></td>
                <td><span className={`small s${i.level} c`}>{STATUS[i.level]}</span></td>
              </tr>))}</tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <div className="head"><h2>Mission patches</h2><span className="small muted">Earned by doing, never by looking healthy</span></div>
        <div className="patches">{p.badges.map(b => (
          <div key={b.id} className={`patch ${b.earned ? '' : 'off'}`} title={b.desc}>
            <Patch id={b.id} earned={b.earned} area={b.area} /><b>{b.name}</b><span className="small dim">{b.earned ? 'Earned' : `${b.progress}/${b.need}`}</span>
          </div>))}</div>
      </section>
    </div>
  )
}
