// Weekly ranking. Read in one glance: who leads and by how much. Position, name and goals done this week only.
// Ranked by goals done (routine goals and check-ins), never by health numbers.
import { api } from '../api/client'
import { Dot } from '../components/People'
import { CountUp, Loading } from '../components/ui'
import { useApi, useSession } from '../state/session'

const MEDAL = ['gold', 'silver', 'bronze']

export default function Ranking() {
  const { me } = useSession()
  const { data } = useApi(() => api.leaderboard(), [])
  if (!data) return <Loading what="ranking" />
  const rows = data.rows
  const top = Math.max(1, ...rows.map(r => r.goals_week))
  if (rows.length === 0) return <div className="page"><p className="waiting">No one is registered on this terminal. Mission Control registers the crew.</p></div>
  const logged = rows.some(r => r.goals_week > 0)
  const lead = rows[0].name?.split(' ')[0]
  const n = rows[0].goals_week

  return (
    <div className="page">
      <div className="head rise">
        <div>
          <h1>{!logged ? 'No goals done yet this week' : rows.length === 1 ? `${lead}: ${n} ${n === 1 ? 'goal' : 'goals'} this week` : `${lead} leads the week with ${n} ${n === 1 ? 'goal' : 'goals'}`}</h1>
          <p className="sub">Goals done in the last 7 days. Health numbers never count.</p>
        </div>
      </div>

      <ol className="board rise" style={{ ['--d' as string]: 2 }}>
        {rows.map((r, i) => (
          <li key={r.crew_id}>
            <div className={`board-row simple ${r.crew_id === me ? 'mine' : ''}`}>
              <span className={`place-badge ${MEDAL[i] ?? ''}`}>{i + 1}</span>
              <Dot p={{ id: r.crew_id, initials: r.initials ?? '', name: r.name ?? '' }} size="sm" me={r.crew_id === me} />
              <span className="board-who"><b>{r.name}{r.crew_id === me && <span className="tag you-tag">you</span>}</b></span>
              <span className="board-xp">
                <span className="bar-track"><i style={{ width: `${(100 * r.goals_week) / top}%` }} /></span>
                <b className="num"><CountUp value={r.goals_week} /><small>{r.goals_week === 1 ? 'goal' : 'goals'}</small></b>
              </span>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}
