// Weekly ranking. Read in one glance: who leads, by how much, and how points are earned.
// Points come from effort only (goals, check-ins, crew missions), never from health numbers.
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Dot } from '../components/People'
import { CountUp, Loading } from '../components/ui'
import { useApi, useSession } from '../state/session'

const MEDAL = ['gold', 'silver', 'bronze']

function Flame() {
  return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2.2 1-3.6 2.2-4.8.3 1.6 1.1 2.5 2.3 2.8C11 9 10.6 6 12 3Z" /></svg>
}

export default function Ranking() {
  const { me } = useSession()
  const { data } = useApi(() => api.leaderboard(), [])
  const nav = useNavigate()
  if (!data) return <Loading what="ranking" />
  const rows = data.rows
  const top = Math.max(1, ...rows.map(r => r.xp_week))

  return (
    <div className="page">
      <div className="head rise">
        <div>
          <h1>{rows[0].name?.split(' ')[0]} leads the week with {rows[0].xp_week.toLocaleString('en-US')} XP</h1>
          <p className="sub">Points come from effort, never from health numbers. A hard day reported honestly earns the same as a good one.</p>
        </div>
      </div>

      <div className="earn rise" style={{ ['--d' as string]: 1 }}>
        <div><b>Daily goals</b><span>10 to 25 XP each, physical and mental</span></div>
        <div><b>Check-ins</b><span>Mood, reaction test, Amsler grid, vitals</span></div>
        <div><b>Crew missions</b><span>Bonus XP for everyone when the crew hits them</span></div>
        <div><b>Streak</b><span>A day counts when 70% of your goals are done</span></div>
      </div>

      <ol className="board rise" style={{ ['--d' as string]: 2 }}>
        {rows.map((r, i) => {
          const ahead = rows[i - 1]
          const gap = ahead ? ahead.xp_week - r.xp_week : r.xp_week - (rows[1]?.xp_week ?? 0)
          return (
            <li key={r.crew_id}>
              <button className={`board-row ${r.crew_id === me ? 'mine' : ''}`} onClick={() => nav(r.crew_id === me ? '/today' : `/crew/${r.crew_id}`)}>
                <span className={`place-badge ${MEDAL[i] ?? ''}`}>{i + 1}</span>
                <Dot p={{ initials: r.initials ?? '', name: r.name ?? '' }} size="sm" me={r.crew_id === me} />
                <span className="board-who">
                  <b>{r.name}{r.crew_id === me && <span className="tag" style={{ marginLeft: 8 }}>you</span>}</b>
                  <span className="small muted">{ahead ? `${gap} XP behind ${ahead.name?.split(' ')[0]}` : `Ahead by ${gap} XP`}</span>
                </span>
                <span className="board-xp">
                  <span className="bar-track"><i style={{ width: `${(100 * r.xp_week) / top}%` }} /></span>
                  <b className="num"><CountUp value={r.xp_week} /><small>XP</small></b>
                </span>
                <span className="board-chips">
                  <span className="chip" title={`${r.need - r.into} XP to level ${r.level + 1}`}>
                    Level {r.level}<span className="mini-bar"><i style={{ width: `${(100 * r.into) / r.need}%` }} /></span>
                  </span>
                  <span className={`chip ${r.streak >= 3 ? 'hot' : ''}`}><Flame />{r.streak} {r.streak === 1 ? 'day' : 'days'}</span>
                  <span className="chip">{r.badges_earned} patches</span>
                </span>
              </button>
            </li>
          )
        })}
      </ol>

      <p className="small muted rise" style={{ ['--d' as string]: 3 }}>
        The crew together: <b className="num" style={{ color: 'var(--ink)' }}>{data.crew_xp_week.toLocaleString('en-US')} XP</b> this week, {data.team_done} of {data.team_total} crew missions done.
      </p>
    </div>
  )
}
