// Weekly ranking. Read in one glance: who leads, by how much, and what counts.
// Ranked by goals done (routine, check-ins, doctor and alert goals), never by health numbers.
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Dot } from '../components/People'
import { CountUp, Loading } from '../components/ui'
import { useApi, useSession } from '../state/session'

const MEDAL = ['gold', 'silver', 'bronze']

export default function Ranking() {
  const { me } = useSession()
  const { data } = useApi(() => api.leaderboard(), [])
  const nav = useNavigate()
  if (!data) return <Loading what="ranking" />
  const rows = data.rows
  const top = Math.max(1, ...rows.map(r => r.goals_week))
  if (rows.length === 0) return <div className="page"><p className="waiting">No one is registered on this terminal. Mission Control registers the crew.</p></div>
  const logged = rows.some(r => r.goals_week > 0)
  const lead = rows[0].name?.split(' ')[0]

  return (
    <div className="page">
      <div className="head rise">
        <div>
          <h1>{!logged ? 'No goals logged yet this week' : rows.length === 1 ? `${lead} has ${rows[0].goals_week} ${rows[0].goals_week === 1 ? 'goal' : 'goals'} done this week` : `${lead} leads the week with ${rows[0].goals_week} goals done`}</h1>
          <p className="sub">Ranked by goals done in the last 7 days. Health numbers never count, and a hard day reported honestly counts the same as a good one.</p>
        </div>
      </div>

      <div className="earn rise" style={{ ['--d' as string]: 1 }}>
        <div><b>Daily goals</b><span>Every goal done counts once, physical or mental</span></div>
        <div><b>Check-ins</b><span>Mood, reaction test, Amsler grid and vitals are goals too</span></div>
        <div><b>Only the routine</b><span>Goals from an alert, the doctor or a suggestion count in your own space, never here</span></div>
        <div><b>Streak</b><span>A day counts when 70% of your goals are done</span></div>
      </div>

      <ol className="board rise" style={{ ['--d' as string]: 2 }}>
        {rows.map((r, i) => {
          const ahead = rows[i - 1]
          const gap = ahead ? ahead.goals_week - r.goals_week : rows[1] ? r.goals_week - rows[1].goals_week : 0
          return (
            <li key={r.crew_id}>
              <button className={`board-row ${r.crew_id === me ? 'mine' : ''}`} onClick={() => nav(r.crew_id === me ? '/me' : `/crew/${r.crew_id}`)}>
                <span className={`place-badge ${MEDAL[i] ?? ''}`}>{i + 1}</span>
                <Dot p={{ id: r.crew_id, initials: r.initials ?? '', name: r.name ?? '' }} size="sm" me={r.crew_id === me} />
                <span className="board-who">
                  <b>{r.name}{r.crew_id === me && <span className="tag you-tag">you</span>}</b>
                  <span className="small muted">{rows.length === 1 ? 'Crew of one' : ahead ? (gap ? `${gap} ${gap === 1 ? 'goal' : 'goals'} behind ${ahead.name?.split(' ')[0]}` : `Level with ${ahead.name?.split(' ')[0]}`) : gap ? `Ahead by ${gap} ${gap === 1 ? 'goal' : 'goals'}` : 'Sharing the lead'}</span>
                </span>
                <span className="board-xp">
                  <span className="bar-track"><i style={{ width: `${(100 * r.goals_week) / top}%` }} /></span>
                  <b className="num"><CountUp value={r.goals_week} /><small>goals</small></b>
                </span>
                <span className="board-chips">
                  <span title="Share of goals done in the last 7 days">{r.completion_7d}% done</span>
                  <span>{r.streak} {r.streak === 1 ? 'day' : 'days'} streak</span>
                  <span>{r.badges_earned} {r.badges_earned === 1 ? 'patch' : 'patches'}</span>
                </span>
              </button>
            </li>
          )
        })}
      </ol>

      <p className="small muted rise" style={{ ['--d' as string]: 3 }}>
        The crew together: <b className="num ink">{data.crew_goals_week.toLocaleString('en-US')} goals</b> in the last 7 days, {data.team_done} of {data.team_total} crew missions done.
      </p>
    </div>
  )
}
