// Career dose against NASA's 600 mSv (V1 4030): earlier flights, then this mission. Personal; the crew pages show the
// mission dose only, which is the same for everyone.
import type { CrewDetail } from '../api/types'
import { doseOrigin } from '../lib/health'
import { useSession } from '../state/session'

export default function RadiationBar({ d, compact = false }: { d: CrewDetail; compact?: boolean }) {
  const { catalog } = useSession()
  const x = d.dose
  if (x.career_msv === undefined || x.prior_msv === undefined) return null
  const limit = x.career_limit_msv
  const pri = Math.min(100, (100 * x.prior_msv) / limit)
  const mis = Math.min(100 - pri, (100 * x.mission_msv) / limit)
  const level = d.systems.skin?.level ?? 0
  const url = catalog?.standards?.document.url
  const storm = d.mission.storm
  return (
    <div className={`rad s${level} ${compact ? 'compact' : ''}`}>
      <div className="rad-bar" role="img" aria-label={`Career dose ${x.career_msv} of ${limit} mSv`}>
        <i className="prior" style={{ width: `${pri}%` }} />
        <i className="now" style={{ width: `${mis}%`, left: `${pri}%` }} />
      </div>
      {!compact && (
        <>
          <ul className="rad-key small">
            <li><i className="prior" /><span>Earlier flights</span><b className="num">{x.prior_msv} mSv</b>{x.prior_estimate && <span className="tag" title={x.prior_source}>estimated</span>}</li>
            <li><i className="now" /><span>This mission</span><b className="num">{x.mission_msv} mSv</b>{doseOrigin(x) && <span className="small dim">{doseOrigin(x)}</span>}</li>
            <li><span className="sp" /><span>Career total</span><b className="num">{x.career_msv} of {limit} mSv</b></li>
          </ul>
          <p className="small muted">
            NASA's career limit counts every flight (<a className="item" href={url} target="_blank" rel="noreferrer">V1 4030</a>).
            {storm && <> A solar storm is active: the limit for one event is {catalog?.standards?.checked.radiation?.spe_msv as number ?? 250} mSv (<a className="item" href={url} target="_blank" rel="noreferrer">V1 4031</a>).</>}
          </p>
        </>
      )}
    </div>
  )
}
