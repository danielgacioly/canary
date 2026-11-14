// The hologram scene: body shell + inner anatomy + platform + particles, with bloom.
// Systems can be hovered, selected, tinted by status and seen through two lenses (physical, mental).
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'
import { buildAnatomy, type Joints, type Part, type SystemId } from './anatomy'
import { bodyMaterial, STATUS_COLOR } from './materials'

export type Lens = 'physical' | 'mental'
export type StatusMap = Partial<Record<SystemId, 0 | 1 | 2>>
const REGIONS = ['head', 'torso', 'arm', 'hand', 'leg', 'foot']
const REGION_SYSTEM: Record<string, SystemId> = { head: 'brain', torso: 'skin', arm: 'muscles', hand: 'muscles', leg: 'muscles', foot: 'muscles' }
const MENTAL: SystemId[] = ['brain']

export interface HoloOptions {
  interactive?: boolean
  autoRotate?: boolean
  onHover?: (sys: SystemId | null, x: number, y: number) => void
  onSelect?: (sys: SystemId | null) => void
}

let assets: Promise<{ geometry: THREE.BufferGeometry; joints: Joints }> | null = null
function loadAssets() {
  assets ??= Promise.all([
    new GLTFLoader().loadAsync('/models/body.glb'),
    fetch('/models/joints.json').then(r => r.json()),
  ]).then(([gltf, j]) => {
    let geometry: THREE.BufferGeometry | null = null
    gltf.scene.traverse(o => { if ((o as THREE.Mesh).isMesh) geometry = (o as THREE.Mesh).geometry })
    if (!geometry) throw new Error('body mesh missing')
    return { geometry, joints: j.joints as Joints }
  })
  return assets
}

export class HologramScene {
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private camera = new THREE.PerspectiveCamera(28, 1, 0.05, 50)
  private controls: OrbitControls
  private composer: EffectComposer
  private bloom: UnrealBloomPass
  private clock = new THREE.Clock()
  private raf = 0
  private ro: ResizeObserver
  private body?: THREE.Mesh<THREE.BufferGeometry, THREE.ShaderMaterial>
  private parts: Part[] = []
  private centers: Partial<Record<SystemId, THREE.Vector3>> = {}
  private animated: THREE.ShaderMaterial[] = []
  private particles?: THREE.Points
  private ray = new THREE.Raycaster()
  private pointer = new THREE.Vector2(9, 9)
  private hovered: SystemId | null = null
  private selected: SystemId | null = null
  private status: StatusMap = {}
  private lens = 0
  private lensTarget = 0
  private reveal = 0
  private homeTarget = new THREE.Vector3(0, 0.92, 0)
  private focus = { target: new THREE.Vector3(0, 0.92, 0), dist: 4.4 }
  private disposed = false
  private downAt = { x: 0, y: 0 }

  constructor(private el: HTMLElement, private opts: HoloOptions = {}) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    // Pure black: through EffectComposer + OutputPass a near-black clear colour gets encoded twice and turns slate grey.
    this.renderer.setClearColor(0x000000, 1)
    el.appendChild(this.renderer.domElement)

    this.camera.position.set(0, 1.05, 4.4)
    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    Object.assign(this.controls, { enableDamping: true, dampingFactor: 0.08, enablePan: false, minDistance: 1.2, maxDistance: 6,
      minPolarAngle: Math.PI * 0.2, maxPolarAngle: Math.PI * 0.78, autoRotate: opts.autoRotate ?? true, autoRotateSpeed: 0.7,
      enableZoom: opts.interactive !== false, enableRotate: opts.interactive !== false })
    this.controls.target.copy(this.homeTarget)
    this.controls.addEventListener('start', () => { this.controls.autoRotate = false; this.zoomUntil = Infinity })

    this.composer = new EffectComposer(this.renderer)
    this.composer.addPass(new RenderPass(this.scene, this.camera))
    this.bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.5, 0.2, 0.14)
    this.composer.addPass(this.bloom)
    this.composer.addPass(new OutputPass())

    this.buildStage()
    if (import.meta.env.DEV) (window as unknown as Record<string, unknown>).__holo = this
    this.ro = new ResizeObserver(() => this.resize())
    this.ro.observe(el)
    this.resize()

    if (opts.interactive !== false) {
      const c = this.renderer.domElement
      c.addEventListener('pointermove', this.onMove)
      c.addEventListener('pointerleave', this.onLeave)
      c.addEventListener('pointerdown', this.onDown)
      c.addEventListener('pointerup', this.onUp)
    }
    this.loop()
  }

  async load() {
    const { geometry, joints } = await loadAssets()
    if (this.disposed) return
    const mat = bodyMaterial()
    this.body = new THREE.Mesh(geometry, mat)
    this.body.userData = { kind: 'body' }
    this.scene.add(this.body)
    this.animated.push(mat)
    const { group, parts, centers } = buildAnatomy(joints)
    this.scene.add(group)
    this.parts = parts
    this.centers = centers
    parts.forEach(p => this.animated.push(p.mesh.material as THREE.ShaderMaterial))
    this.applyStatus()
  }

  private buildStage() {
    const ringMat = (op: number) => new THREE.MeshBasicMaterial({ color: '#5ef2ff', transparent: true, opacity: op, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide })
    const floor = new THREE.Group()
    const r1 = new THREE.Mesh(new THREE.RingGeometry(0.42, 0.425, 96), ringMat(0.55))
    const r2 = new THREE.Mesh(new THREE.RingGeometry(0.55, 0.552, 128), ringMat(0.25))
    const disc = new THREE.Mesh(new THREE.CircleGeometry(0.42, 64), ringMat(0.04))
    floor.add(r1, r2, disc)
    floor.rotation.x = -Math.PI / 2
    floor.position.y = 0.002
    this.scene.add(floor)
    this.scene.userData.floor = floor

    const n = 240, pos = new Float32Array(n * 3), seed = new Float32Array(n)
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, r = 0.3 + Math.random() * 0.75
      pos.set([Math.cos(a) * r, Math.random() * 2.1, Math.sin(a) * r], i * 3)
      seed[i] = Math.random()
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    g.setAttribute('seed', new THREE.BufferAttribute(seed, 1))
    this.particles = new THREE.Points(g, new THREE.PointsMaterial({ color: '#7cf3ff', size: 0.008, transparent: true, opacity: 0.3, blending: THREE.AdditiveBlending, depthWrite: false }))
    this.scene.add(this.particles)
  }

  setStatus(s: StatusMap) { this.status = s; this.applyStatus() }
  setLens(l: Lens) { this.lensTarget = l === 'mental' ? 1 : 0; this.applyStatus() }
  select(sys: SystemId | null) {
    this.selected = sys
    this.zoomUntil = 0
    const c = sys ? this.centers[sys] : null
    this.focus = c ? { target: c.clone(), dist: sys === 'muscles' || sys === 'skeleton' || sys === 'skin' ? 3.2 : 1.9 } : { target: this.homeTarget.clone(), dist: 4.4 }
    this.applyStatus()
  }

  private applyStatus() {
    if (!this.body) return
    const u = this.body.material.uniforms
    REGIONS.forEach((r, i) => {
      const sys = REGION_SYSTEM[r]
      const lvl = this.status[sys] ?? 0
      const c = STATUS_COLOR[lvl]
      ;(u.uTint.value[i] as THREE.Vector4).set(c.r, c.g, c.b, lvl ? 0.55 : 0)
      u.uBoost.value[i] = sys === this.hovered ? 0.6 : sys === this.selected ? 0.9 : 0
    })
    for (const p of this.parts) {
      const m = p.mesh.material as THREE.ShaderMaterial
      const lvl = this.status[p.system] ?? 0
      m.uniforms.uColor.value.copy(lvl ? STATUS_COLOR[lvl] : m.uniforms.uBase.value)
      m.uniforms.uPulse.value = lvl === 2 ? 1 : lvl === 1 ? 0.4 : 0
      m.uniforms.uBoost.value = p.system === this.hovered ? 0.7 : p.system === this.selected ? 1 : 0
    }
  }

  private pick(): SystemId | null {
    this.ray.setFromCamera(this.pointer, this.camera)
    const targets = [...this.parts.filter(p => p.kind !== 'nerve' || this.lens > 0.5).map(p => p.mesh), ...(this.body ? [this.body] : [])]
    const hits = this.ray.intersectObjects(targets, false)
    if (!hits.length) return null
    const organ = hits.find(h => h.object.userData.kind === 'organ')
    if (organ) return organ.object.userData.system
    const other = hits.find(h => h.object.userData.kind !== 'body')
    if (other) return other.object.userData.system
    const h = hits[0]
    if (h.face && this.body) {
      const r = (this.body.geometry.getAttribute('_region') as THREE.BufferAttribute).getX(h.face.a)
      const sys = REGION_SYSTEM[REGIONS[Math.round(r)]]
      return this.lens > 0.5 && !MENTAL.includes(sys) ? null : sys
    }
    return null
  }

  private onMove = (e: PointerEvent) => {
    const r = this.renderer.domElement.getBoundingClientRect()
    this.pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
    const sys = this.pick()
    if (sys !== this.hovered) { this.hovered = sys; this.applyStatus() }
    this.renderer.domElement.style.cursor = sys ? 'pointer' : 'grab'
    this.opts.onHover?.(sys, e.clientX - r.left, e.clientY - r.top)
  }
  private onLeave = () => { this.hovered = null; this.applyStatus(); this.opts.onHover?.(null, 0, 0) }
  private onDown = (e: PointerEvent) => { this.downAt = { x: e.clientX, y: e.clientY } }
  private onUp = (e: PointerEvent) => {
    if (Math.hypot(e.clientX - this.downAt.x, e.clientY - this.downAt.y) > 5) return // it was a drag
    const r = this.renderer.domElement.getBoundingClientRect()
    this.pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
    const sys = this.pick()
    this.opts.onSelect?.(sys)
  }

  private resize() {
    const w = Math.max(1, this.el.clientWidth), h = Math.max(1, this.el.clientHeight)
    this.renderer.setSize(w, h, false)
    this.composer.setSize(w, h)
    this.bloom.resolution.set(w / 2, h / 2)
    this.camera.aspect = w / h
    this.camera.fov = w / h < 0.75 ? 36 : 28
    this.camera.updateProjectionMatrix()
  }

  private loop = () => {
    if (this.disposed) return
    this.raf = requestAnimationFrame(this.loop)
    const dt = Math.min(0.05, this.clock.getDelta()), t = this.clock.elapsedTime
    this.lens += (this.lensTarget - this.lens) * Math.min(1, dt * 4)
    if (this.body) this.reveal = Math.min(2.2, this.reveal + dt * 1.1)
    for (const m of this.animated) {
      if (m.uniforms.uTime) m.uniforms.uTime.value = t
      if (m.uniforms.uReveal) m.uniforms.uReveal.value = this.reveal
    }
    if (this.body) this.body.material.uniforms.uLens.value = this.lens
    for (const p of this.parts) {
      const m = p.mesh.material as THREE.ShaderMaterial
      const mental = p.kind === 'nerve' || p.system === 'brain'
      const base = p.kind === 'nerve' ? 0.25 + 1.0 * this.lens : mental ? 0.9 + 0.4 * this.lens : 0.9 - 0.68 * this.lens
      m.uniforms.uOpacity.value = base * (p.kind === 'bone' ? 0.8 : 1)
      if (p.system === 'heart' && p.kind === 'organ') p.mesh.scale.setScalar(1).multiply(new THREE.Vector3(0.042, 0.05, 0.04)).multiplyScalar(1 + 0.06 * Math.max(0, Math.sin(t * 7.2)) ** 6)
    }
    if (this.particles) {
      const p = this.particles.geometry.getAttribute('position') as THREE.BufferAttribute
      for (let i = 0; i < p.count; i++) { let y = p.getY(i) + dt * 0.04; if (y > 2.1) y = 0; p.setY(i, y) }
      p.needsUpdate = true
    }
    // ease the camera toward the selected system
    this.controls.target.lerp(this.focus.target, Math.min(1, dt * 3))
    const d = this.camera.position.distanceTo(this.controls.target)
    if (Math.abs(d - this.focus.dist) > 0.01 && !this.userZooming()) {
      const dir = this.camera.position.clone().sub(this.controls.target).normalize()
      this.camera.position.copy(this.controls.target).addScaledVector(dir, d + (this.focus.dist - d) * Math.min(1, dt * 3))
    }
    this.controls.update()
    this.composer.render()
  }
  private zoomUntil = 0
  private userZooming() { return performance.now() < this.zoomUntil }

  dispose() {
    this.disposed = true
    cancelAnimationFrame(this.raf)
    this.ro.disconnect()
    this.controls.dispose()
    this.scene.traverse(o => {
      const m = o as THREE.Mesh
      if (m.isMesh || (o as THREE.Points).isPoints) {
        if (m !== this.body) m.geometry?.dispose()
        ;(Array.isArray(m.material) ? m.material : [m.material]).forEach(x => x?.dispose())
      }
    })
    this.composer.dispose()
    this.renderer.dispose()
    this.renderer.domElement.remove()
  }
}
