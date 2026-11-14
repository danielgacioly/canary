// Twinkling starfield behind the full-screen pages (intro, mission setup). Put it inside a `.intro` container.
import { useMemo } from 'react'

export default function Stars() {
  const stars = useMemo(() => Array.from({ length: 160 }, () => ({ x: Math.random() * 100, y: Math.random() * 100, r: Math.random() * 1.4 + 0.3, d: 2.5 + Math.random() * 4, o: Math.random() * 3 })), [])
  return (
    <svg className="stars" aria-hidden="true">
      {stars.map((s, k) => (
        <circle key={k} cx={`${s.x}%`} cy={`${s.y}%`} r={s.r} fill="#dfe7f5">
          <animate attributeName="opacity" values=".1;.85;.1" dur={`${s.d}s`} begin={`${s.o}s`} repeatCount="indefinite" />
        </circle>
      ))}
    </svg>
  )
}
