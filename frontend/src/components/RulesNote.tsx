// RULE-01: the rules behind the alerts and risks are heuristic until a clinical reviewer signs them. One quiet line where
// they are explained, not one per row.
import type { RulesReview } from '../api/types'

export default function RulesNote({ review }: { review?: RulesReview }) {
  if (!review || review.unreviewed === 0) return null
  return (
    <p className="rules-note small dim" title={`${review.reviewed} of ${review.total} rules have a reviewer`}>
      Heuristic · not clinically reviewed
    </p>
  )
}
