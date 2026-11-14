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
  const medal = ['var(--gold)', '#c9ccd4', '#c08457']
  return (
    <div className="page">
      <div className="head rise"><div><h1>Effort, not vital signs.</h1>
        <p className="sub">XP comes from goals and check-ins, never from health numbers, so nobody gains by hiding a symptom.</p></div></div>

      <div className="grid g3">
        {data.rows.slice(0, 3).map((r, i) => (
          <button key={r.crew_id} className="detail-card rise row" style={{ ['--d' as string]: i, gap: 16, textAlign: 'left', borderTop: `3px solid ${medal[i]}` }} onClick={() => nav(`/crew/${r.crew_id}`)}>
            <span className="num" style={{ font: '600 36px var(--f-display)', color: medal[i], width: 30 }}>{i + 1}</span>
            <Avatar initials={r.initials ?? ''} size="lg" />
            <div className="grow"><b>{r.name}</b><div className="small muted">{r.role}</div></div>
            <div style={{ textAlign: 'right' }}><b className="num" style={{ font: '600 26px var(--f-display)' }}><CountUp value={r.xp_week} /></b><div className="small dim">XP this week</div></div>
          </button>
        ))}
      </div>

      <section className="detail-card rise" style={{ ['--d' as string]: 3, padding: 8 }}>
        <div className="scroll"><table className="t">
          <thead><tr><th style={{ width: 40 }}>#</th><th>Crew member</th><th style={{ width: '36%' }}>XP this week</th><th>Level</th><th>Streak</th><th>Goals, 7 days</th><th>Patches</th></tr></thead>
          <tbody>{data.rows.map(r => (
            <tr key={r.crew_id} className="click" onClick={() => nav(`/crew/${r.crew_id}`)}>
              <td className="num" style={{ fontSize: 18, fontWeight: 600, color: medal[(r.rank ?? 9) - 1] ?? 'var(--muted)' }}>{r.rank}</td>
              <td><div className="row"><Avatar initials={r.initials ?? ''} /><div><b>{r.name}</b>{r.crew_id === me && <span className="tag" style={{ marginLeft: 8 }}>you</span>}<div className="small muted">{r.role}</div></div></div></td>
              <td><div className="row"><div className="bar-track grow" style={{ ['--pc' as string]: r.rank === 1 ? 'var(--gold)' : 'var(--accent)' }}><i style={{ width: `${(100 * r.xp_week) / top}%` }} /></div><span className="num" style={{ minWidth: 44, textAlign: 'right' }}>{r.xp_week}</span></div></td>
              <td className="num">{r.level}</td><td className="num">{r.streak} d</td><td className="num">{r.completion_7d}%</td><td className="num">{r.badges_earned}</td>
            </tr>))}</tbody>
        </table></div>
      </section>
      <p className="small dim">Crew XP this week: {data.crew_xp_week.toLocaleString('en-US')} · crew missions done: {data.team_done} of {data.team_total}</p>
    </div>
  )
}
