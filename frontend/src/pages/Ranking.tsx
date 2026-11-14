import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Avatar } from '../components/ui'
import { useApi, useSession } from '../state/session'

/** Weekly ranking, shown as a tab of Goals. */
export default function RankingView() {
  const { me } = useSession()
  const { data } = useApi(() => api.leaderboard(), [])
  const nav = useNavigate()
  if (!data) return <span className="lbl">Loading ranking…</span>
  const top = Math.max(1, ...data.rows.map(r => r.xp_week))
  return (
    <div className="col" style={{ gap: 16 }}>
      <p className="muted" style={{ maxWidth: 680 }}>Ranked by XP this week. XP comes from goals and check-ins, never from health numbers, so nobody gains by hiding a symptom.</p>
      <div className="card" style={{ padding: 8 }}>
        <div className="scroll"><table className="t">
          <thead><tr><th style={{ width: 40 }}>#</th><th>Crew member</th><th style={{ width: '38%' }}>XP this week</th><th>Level</th><th>Streak</th><th>Goals, 7 days</th></tr></thead>
          <tbody>{data.rows.map(r => (
            <tr key={r.crew_id} className="click" onClick={() => nav(`/crew/${r.crew_id}`)}>
              <td className="num" style={{ fontSize: 18, fontWeight: 600, color: r.rank === 1 ? 'var(--gold)' : 'var(--muted)' }}>{r.rank}</td>
              <td><div className="row"><Avatar initials={r.initials ?? ''} /><div><b>{r.name}</b>{r.crew_id === me && <span className="tag" style={{ marginLeft: 8 }}>you</span>}<div className="small muted">{r.role}</div></div></div></td>
              <td><div className="row"><div className="bar-track grow" style={{ ['--pc' as string]: r.rank === 1 ? 'var(--gold)' : 'var(--accent)' }}><i style={{ width: `${(100 * r.xp_week) / top}%` }} /></div><span className="num" style={{ minWidth: 44, textAlign: 'right' }}>{r.xp_week}</span></div></td>
              <td className="num">{r.level}</td>
              <td className="num">{r.streak} d</td>
              <td className="num">{r.completion_7d}%</td>
            </tr>))}</tbody>
        </table></div>
      </div>
      <p className="small dim">Crew XP this week: {data.crew_xp_week.toLocaleString('en-US')} · crew missions done: {data.team_done} of {data.team_total}</p>
    </div>
  )
}
