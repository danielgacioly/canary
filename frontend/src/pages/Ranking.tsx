import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Avatar, CountUp, Loading } from '../components/ui'
import { useApi, useSession } from '../state/session'

export default function Ranking() {
  const { me } = useSession()
  const { data } = useApi(() => api.leaderboard(), [])
  const nav = useNavigate()
  if (!data) return <Loading what="ranking" />
  const top = Math.max(1, ...data.rows.map(r => r.xp_week))
  return (
    <div className="page">
      <div className="hello">
        <div className="col" style={{ gap: 8 }}><span className="lbl">Weekly ranking</span><h1>Effort, not vital signs.</h1>
          <p className="muted" style={{ maxWidth: 640 }}>XP comes from goals done and check-ins sent. Health numbers never count, and a hard day reported honestly earns the same as a good one, so nobody gains by hiding a symptom.</p></div>
        <div className="row right" style={{ gap: 22 }}>
          <div className="kpi"><span className="lbl">Crew XP this week</span><b className="num"><CountUp value={data.crew_xp_week} /></b></div>
          <div className="kpi"><span className="lbl">Crew missions</span><b className="num">{data.team_done}<small>/{data.team_total}</small></b></div>
        </div>
      </div>

      <div className="grid g3">
        {data.rows.slice(0, 3).map((r, i) => (
          <div key={r.crew_id} className="card" style={{ display: 'flex', alignItems: 'center', gap: 16, borderColor: i === 0 ? 'rgba(255,207,92,.45)' : undefined }}>
            <span className="rank-n" style={{ fontSize: 34, color: ['var(--gold)', '#d9e2ef', '#d39a6a'][i] }}>{i + 1}</span>
            <Avatar initials={r.initials ?? ''} size="lg" />
            <div className="grow"><b>{r.name}</b><div className="lbl">{r.role}</div><div className="small muted" style={{ marginTop: 4 }}>{r.xp_week} XP · {r.streak}d streak</div></div>
          </div>))}
      </div>

      <section className="card">
        <div className="scroll">
          <table className="t">
            <thead><tr><th>#</th><th>Crew member</th><th>Level</th><th style={{ width: '32%' }}>XP this week</th><th>Physical / mental</th><th>Streak</th><th>Goals 7d</th><th>Patches</th></tr></thead>
            <tbody>{data.rows.map(r => (
              <tr key={r.crew_id} className={`click r${r.rank}`} onClick={() => nav(`/crew/${r.crew_id}`)} style={r.crew_id === me ? { background: 'rgba(94,242,255,.04)' } : undefined}>
                <td><span className="rank-n">{r.rank}</span></td>
                <td><div className="row"><Avatar initials={r.initials ?? ''} /><div><b>{r.name}</b>{r.crew_id === me && <span className="tag" style={{ marginLeft: 8 }}>you</span>}<div className="lbl">{r.role}</div></div></div></td>
                <td><span className="level-chip">{r.level}</span></td>
                <td><div className="row"><div className="prog grow" style={{ ['--pc' as string]: 'var(--gold)' }}><i style={{ width: `${(100 * r.xp_week) / top}%` }} /></div><span className="num" style={{ minWidth: 48, textAlign: 'right' }}>{r.xp_week}</span></div></td>
                <td className="num"><span style={{ color: 'var(--physical)' }}>{r.xp_week_by_area.physical}</span> / <span style={{ color: 'var(--mental)' }}>{r.xp_week_by_area.mental}</span></td>
                <td className="num">{r.streak}d</td>
                <td className="num">{r.completion_7d}%</td>
                <td className="num">{r.badges_earned}</td>
              </tr>))}</tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
