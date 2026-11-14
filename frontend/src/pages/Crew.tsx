import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { TeamRow } from '../components/GoalItems'
import { Avatar, Gauge, Loading, Pill } from '../components/ui'
import { useApi, useSession } from '../state/session'

const SYS_ORDER = ['brain', 'heart', 'lungs', 'skeleton', 'muscles', 'eyes', 'kidneys', 'gut', 'immune', 'skin']

export default function Crew() {
  const { catalog } = useSession()
  const { data } = useApi(() => api.crew(), [])
  const nav = useNavigate()
  if (!data || !catalog) return <Loading what="crew" />
  const names = Object.fromEntries(data.crew.map(c => [c.id, c.name]))
  const worst = Math.max(...data.crew.map(c => c.level)) as 0 | 1 | 2
  return (
    <div className="page">
      <div className="hello">
        <div className="col" style={{ gap: 8 }}><span className="lbl">{data.mission.day_label} · {data.mission.place.name}</span><h1>Crew readiness</h1></div>
        <div className="right"><Pill level={worst}>{worst ? `${data.crew.filter(c => c.level).length} need attention` : 'Whole crew on track'}</Pill></div>
      </div>

      <div className="grid g4">
        <div className="card row" style={{ gap: 16 }}><Gauge value={data.crew_readiness.physical} color="var(--physical)" size={84} /><div className="kpi"><span className="lbl">Crew physical</span><span className="small muted">Average of four</span></div></div>
        <div className="card row" style={{ gap: 16 }}><Gauge value={data.crew_readiness.mental} color="var(--mental)" size={84} /><div className="kpi"><span className="lbl">Crew mental</span><span className="small muted">Average of four</span></div></div>
        <div className="card kpi"><span className="lbl">Mission dose (simulated)</span><b>{data.dose.mission_msv}<small>mSv</small></b>
          <div className="prog" style={{ ['--pc' as string]: 'var(--gold)' }}><i style={{ width: `${Math.min(100, data.dose.pct_of_limit)}%` }} /></div>
          <span className="small muted">{data.dose.pct_of_limit}% of the {data.dose.career_limit_msv} mSv career limit</span></div>
        <div className={`card kpi s${data.space_weather.active ? 2 : 0}`}><span className="lbl">Space weather · NASA DONKI</span><b className="c">{data.space_weather.headline}</b>
          <span className="small muted">Replay window: {data.space_weather.sep_events} particle events, Kp max {data.space_weather.kp_max}</span></div>
      </div>

      <div className="grid g4">
        {data.crew.map(c => (
          <article key={c.id} className={`card crewcard s${c.level}`} onClick={() => nav(`/crew/${c.id}`)}>
            <div className="row"><Avatar initials={c.initials} size="lg" /><div className="grow"><b style={{ fontSize: 16 }}>{c.name}</b><div className="lbl">{c.role}</div></div></div>
            <div className="dual">
              <div className="col" style={{ gap: 4 }}><span className="lbl" style={{ color: 'var(--physical)' }}>Physical</span><b className="num" style={{ fontSize: 22 }}>{c.areas.physical.score}</b><span className={`small s${c.areas.physical.level} c`}>{c.areas.physical.status}</span></div>
              <div className="col" style={{ gap: 4 }}><span className="lbl" style={{ color: 'var(--mental)' }}>Mental</span><b className="num" style={{ fontSize: 22 }}>{c.areas.mental.score}</b><span className={`small s${c.areas.mental.level} c`}>{c.areas.mental.status}</span></div>
            </div>
            <div className="small" style={{ minHeight: 40 }}>{c.top_alert ? <span className={`s${c.level} c`}>{c.top_alert}</span> : <span className="muted">Nothing outside personal normal.</span>}</div>
            <div className="row small dim"><span>LVL {c.level_xp}</span><span>·</span><span>{c.xp_week} XP this week</span><span>·</span><span>{c.streak}d streak</span></div>
          </article>
        ))}
      </div>

      <section className="card">
        <div className="head"><h2>Body systems by person</h2><span className="small muted">Each square compares that person with their own normal</span></div>
        <div className="scroll">
          <table className="t matrix">
            <thead><tr><th>Crew</th>{SYS_ORDER.map(s => <th key={s} style={{ textAlign: 'center' }}>{catalog.systems[s].name.split(' ')[0]}</th>)}</tr></thead>
            <tbody>{data.crew.map(c => (
              <tr key={c.id} className="click" onClick={() => nav(`/crew/${c.id}`)}>
                <td><div className="row"><Avatar initials={c.initials} /><span>{c.name}</span></div></td>
                {SYS_ORDER.map(s => <td key={s} className="cell"><span className={`sq s${c.systems[s]}`} title={`${catalog.systems[s].name}: ${['On track', 'Watch', 'Act'][c.systems[s]]}`} /></td>)}
              </tr>))}</tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <div className="head"><h2>Crew missions this week</h2><span className="tag">{data.team.filter(t => t.done).length}/{data.team.length} complete</span></div>
        <div className="grid g2">{data.team.map(t => <TeamRow key={t.id} t={t} names={names} />)}</div>
      </section>
    </div>
  )
}
