import { useEffect, useRef, useState } from 'react'
import type { SystemId } from './anatomy'
import { HologramScene, type Lens, type StatusMap } from './scene'

interface Props {
  status?: StatusMap
  lens?: Lens
  selected?: SystemId | null
  onSelect?: (s: SystemId | null) => void
  names?: Record<string, string>
  levels?: Record<string, number>
  interactive?: boolean
  autoRotate?: boolean
  className?: string
  children?: React.ReactNode
}

const STATUS = ['On track', 'Watch', 'Act']

export default function BodyHologram({ status = {}, lens = 'physical', selected = null, onSelect, names = {}, levels = {},
  interactive = true, autoRotate = true, className = 'holo-wrap', children }: Props) {
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

  return (
    <div className={className}>
      <div ref={host} style={{ position: 'absolute', inset: 0 }} />
      <div className="scan" />
      <div className="holo-hud">
        <i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
      </div>
      {!ready && !failed && <div className="holo-loading"><span className="lbl">Calibrating hologram…</span></div>}
      {failed && <div className="holo-loading"><span className="lbl">3D needs WebGL 2. Health data is still shown beside.</span></div>}
      {tip && (
        <div className="holo-tip" style={{ left: tip.x, top: tip.y }}>
          <div className="row" style={{ gap: 8 }}>
            <span className={`dot s${levels[tip.sys] ?? 0}`} />
            <b>{names[tip.sys] ?? tip.sys}</b>
            <span className={`small s${levels[tip.sys] ?? 0} c`}>{STATUS[levels[tip.sys] ?? 0]}</span>
          </div>
        </div>
      )}
      {children}
    </div>
  )
}
