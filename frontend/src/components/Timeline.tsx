// The itinerary as a thin bar plus a legend underneath. Labels never sit inside the bar,
// so a 1-day launch leg reads as clearly as a 500-day surface stay.
import type { Leg } from '../api/types'

interface Props {
  legs: Leg[]
  places: Record<string, { name: string }>
  now?: number | null
  nowLabel?: string
  selected?: number | null
  onSelect?: (i: number) => void
  compact?: boolean
}

export default function Timeline({ legs, places, now = null, nowLabel, selected = null, onSelect, compact = false }: Props) {
  const lo = legs[0].start, hi = legs[legs.length - 1].end, span = hi - lo + 1
  const pct = (d: number) => (100 * (Math.min(hi + 1, Math.max(lo, d)) - lo)) / span
  const nowPct = now === null ? null : pct(now + 0.5)
  const current = now === null ? -1 : legs.findIndex(l => now >= l.start && now <= l.end)
  const Tag = onSelect ? 'button' : 'div'
  return (
    <div className={`tl ${compact ? 'compact' : ''}`}>
      <div className="tl-bar" role="img" aria-label={`Itinerary from day ${lo} to day ${hi}`}>
        {legs.map((l, i) => (
          <span key={i} className={`tl-seg p-${l.location} ${selected === i ? 'on' : ''}`}
            style={{ left: `${pct(l.start)}%`, width: `${pct(l.end + 1) - pct(l.start)}%`, ['--k' as string]: i }} />
        ))}
        {nowPct !== null && (
          <i className={`tl-now ${nowPct < 8 ? 'l' : nowPct > 92 ? 'r' : ''}`} style={{ left: `${nowPct}%` }}>
            <span>{nowLabel ?? `Day ${now}`}</span>
          </i>
        )}
      </div>
      <div className="tl-legend">
        {legs.map((l, i) => (
          <Tag key={i} className={`tl-item p-${l.location} ${selected === i ? 'on' : ''} ${i === current ? 'cur' : ''}`}
            {...(onSelect ? { onClick: () => onSelect(i), type: 'button' as const } : {})}>
            <span className="pc-dot" />
            <span className="tl-text">
              <b>{l.label || places[l.location]?.name}</b>
              {!compact && <span className="small muted">{places[l.location]?.name}</span>}
              <span className="small dim num">{compact ? <span>{l.end - l.start + 1} d</span> : <><span>Day {l.start} to {l.end}</span> <span>· {l.end - l.start + 1} d</span></>}</span>
            </span>
            {i === current && !compact && <span className="tag now-tag">Now</span>}
          </Tag>
        ))}
      </div>
    </div>
  )
}
