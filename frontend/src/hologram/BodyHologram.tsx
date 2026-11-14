import { useEffect, useRef, useState } from 'react'
import type { SystemId } from './anatomy'
import { HologramScene, type Lens, type StatusMap } from './scene'

interface Props {
  status?: StatusMap
  lens?: Lens
  selected?: SystemId | null
  onSelect?: (s: SystemId | null) => void
  names?: Record<string, string>
  interactive?: boolean
  autoRotate?: boolean
  className?: string
  children?: React.ReactNode
}

const STATUS = ['On track', 'Watch', 'Act']

export default function BodyHologram({ status = {}, lens = 'physical', selected = null, onSelect, names = {},
  interactive = true, autoRotate = true, className = 'bodycard', children }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const scene = useRef<HologramScene | null>(null)
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)
  const [tip, setTip] = useState<{ sys: SystemId; x: number; y: number } | null>(null)
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect

  useEffect(() => {
    if (!host.current) return
    let s: HologramScene
    try {
      s = new HologramScene(host.current, {
        interactive, autoRotate,
        onHover: (sys, x, y) => setTip(sys ? { sys, x, y } : null),
        onSelect: sys => onSelectRef.current?.(sys),
      })
    } catch {
      setFailed(true)
      return
    }
    scene.current = s
    s.load().then(() => setReady(true)).catch(() => setFailed(true))
    return () => { s.dispose(); scene.current = null }
  }, [interactive, autoRotate])

  useEffect(() => { scene.current?.setStatus(status) }, [status, ready])
  useEffect(() => { scene.current?.setLens(lens) }, [lens, ready])
  useEffect(() => { scene.current?.select(selected) }, [selected, ready])

  const lvl = tip ? status[tip.sys] ?? 0 : 0
  return (
    <div className={className}>
      <div ref={host} style={{ position: 'absolute', inset: 0 }} />
      {!ready && !failed && <div className="holo-loading">Loading body…</div>}
      {failed && <div className="holo-loading">The 3D body needs WebGL 2. Your data is listed beside it.</div>}
      {tip && (
        <div className="holo-tip" style={{ left: tip.x, top: tip.y }}>
          <b>{names[tip.sys] ?? tip.sys}</b> <span className={`s${lvl} c`}>· {STATUS[lvl]}</span>
        </div>
      )}
      {children}
    </div>
  )
}
