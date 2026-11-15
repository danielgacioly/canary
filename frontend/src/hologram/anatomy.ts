// Inner anatomy of the hologram. The bones and organs are real meshes (BodyParts3D, fitted to the body by
// tools/build_anatomy_model.py and stored in public/models/anatomy.glb); if that file cannot be loaded the
// same scene is built procedurally from the MakeHuman joint positions (joints.json, metres), as before.
// Vessels of the limbs and the nerves are always drawn procedurally. This is a readable map of the body
// systems, not a medical atlas.
import * as THREE from 'three'
import type { GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { flowMaterial, glowMaterial } from './materials'

export type Vec = [number, number, number]
export type Joints = Record<string, Vec>
export type SystemId = 'brain' | 'eyes' | 'heart' | 'lungs' | 'skeleton' | 'muscles' | 'gut' | 'kidneys' | 'immune' | 'skin'

export const SYSTEM_COLOR: Record<SystemId, string> = {
  brain: '#b28bff', eyes: '#7cf3ff', heart: '#ff5fa8', lungs: '#6fd8ff', skeleton: '#c6fbff',
  muscles: '#ff7ad9', gut: '#ffd36b', kidneys: '#ffa860', immune: '#9dff9a', skin: '#5ef2ff',
}

const v = (p: Vec) => new THREE.Vector3(...p)
const UP = new THREE.Vector3(0, 1, 0)

export interface Part { mesh: THREE.Mesh; system: SystemId; kind: 'organ' | 'bone' | 'vessel' | 'nerve' }

/** Look of the real structures that are not plain glowing surfaces: light travelling along vessels and airways. */
const FLOW: Record<string, { color: string; speed: number; opacity: number }> = {
  aorta: { color: '#ff4f8e', speed: 0.7, opacity: 1 }, pulmonary_trunk: { color: '#ff4f8e', speed: 0.7, opacity: 1 },
  vena_cava: { color: '#6f8dff', speed: 0.45, opacity: 1 }, coronaries: { color: '#ff4f8e', speed: 0.9, opacity: 1 },
  arteries_trunk: { color: '#ff4f8e', speed: 0.7, opacity: 1 },
  arteries_arm_left: { color: '#ff4f8e', speed: 0.7, opacity: 1 }, arteries_arm_right: { color: '#ff4f8e', speed: 0.7, opacity: 1 },
  arteries_leg_left: { color: '#ff4f8e', speed: 0.7, opacity: 1 }, arteries_leg_right: { color: '#ff4f8e', speed: 0.7, opacity: 1 },
  airways_left: { color: SYSTEM_COLOR.lungs, speed: 0.35, opacity: 1 }, airways_right: { color: SYSTEM_COLOR.lungs, speed: 0.35, opacity: 1 },
  trachea: { color: SYSTEM_COLOR.lungs, speed: 0.35, opacity: 1 },
  lung_vessels_left: { color: '#8fe6ff', speed: 0.5, opacity: 0.8 }, lung_vessels_right: { color: '#8fe6ff', speed: 0.5, opacity: 0.8 },
}

/** The meshes of anatomy.glb as plain float geometry in world space (the file is meshopt-quantised, with a transform per node). */
function readReal(gltf: GLTF) {
  gltf.scene.updateMatrixWorld(true)
  const out: { name: string; geometry: THREE.BufferGeometry; system: SystemId; kind: Part['kind']; color?: string; glow: number }[] = []
  gltf.scene.traverse(o => {
    const m = o as THREE.Mesh
    if (!m.isMesh) return
    const { system, kind, color, glow } = m.userData as { system?: SystemId; kind?: Part['kind']; color?: string; glow?: number }
    if (!system || !SYSTEM_COLOR[system] || !kind) return
    const src = m.geometry
    const g = new THREE.BufferGeometry()
    const floats = (a: THREE.BufferAttribute | THREE.InterleavedBufferAttribute) => {
      const f = new Float32Array(a.count * a.itemSize)
      for (let i = 0; i < a.count; i++) {
        f[i * a.itemSize] = a.getX(i); f[i * a.itemSize + 1] = a.getY(i)
        if (a.itemSize > 2) f[i * a.itemSize + 2] = a.getZ(i)
      }
      return new THREE.BufferAttribute(f, a.itemSize)
    }
    g.setAttribute('position', floats(src.getAttribute('position')))
    g.setAttribute('normal', floats(src.getAttribute('normal')))
    if (src.getAttribute('uv')) g.setAttribute('uv', floats(src.getAttribute('uv')))
    g.setIndex(src.index)
    g.applyMatrix4(m.matrixWorld)
    out.push({ name: m.name, geometry: g, system, kind, color, glow: glow ?? 1 })
  })
  if (!out.length) throw new Error('anatomy.glb has no tagged meshes')
  return { meshes: out, spine: ((gltf.scene.userData.spine ?? []) as Vec[]) }
}

export function buildAnatomy(J: Joints, gltf?: GLTF | null) {
  const real = gltf ? readReal(gltf) : null
  const group = new THREE.Group()
  const parts: Part[] = []
  const centers: Partial<Record<SystemId, THREE.Vector3>> = {}

  const add = (mesh: THREE.Mesh, system: SystemId, kind: Part['kind']) => {
    mesh.userData = { system, kind }
    group.add(mesh)
    parts.push({ mesh, system, kind })
    return mesh
  }
  const organ = (system: SystemId, c: Vec, r: Vec, color = SYSTEM_COLOR[system], detail = 3, noise = 0) => {
    const g = new THREE.IcosahedronGeometry(1, detail)
    if (noise) {
      const p = g.attributes.position as THREE.BufferAttribute
      for (let i = 0; i < p.count; i++) {
        const x = p.getX(i), y = p.getY(i), z = p.getZ(i)
        const n = 1 + noise * (Math.sin(x * 9.1 + y * 3.3) * Math.cos(z * 7.7 + x * 2.1) + 0.5 * Math.sin(y * 17 + z * 11))
        p.setXYZ(i, x * n, y * n, z * n)
      }
      g.computeVertexNormals()
    }
    const m = new THREE.Mesh(g, glowMaterial(color, 0.9))
    m.position.set(...c); m.scale.set(...r)
    centers[system] ??= new THREE.Vector3(...c)
    return add(m, system, 'organ')
  }
  const bone = (a: THREE.Vector3, b: THREE.Vector3, r: number, system: SystemId = 'skeleton') => {
    const len = a.distanceTo(b)
    const m = new THREE.Mesh(new THREE.CapsuleGeometry(r, Math.max(0.001, len - 2 * r), 3, 8), glowMaterial(SYSTEM_COLOR[system], 0.75))
    m.position.copy(a).add(b).multiplyScalar(0.5)
    m.quaternion.setFromUnitVectors(UP, b.clone().sub(a).normalize())
    return add(m, system, 'bone')
  }
  const tube = (pts: THREE.Vector3[], r: number, system: SystemId, kind: 'vessel' | 'nerve' | 'bone', color: string, speed = 0.5, opacity = 1) => {
    const curve = new THREE.CatmullRomCurve3(pts)
    const mat = kind === 'bone' ? glowMaterial(color, 0.75) : flowMaterial(color, speed, opacity)
    const m = new THREE.Mesh(new THREE.TubeGeometry(curve, Math.max(12, pts.length * 10), r, 6, false), mat)
    return add(m, system, kind)
  }

  const neck = v(J.neck), pelvis = v(J.pelvis), head = v(J.head), top = v(J['head-2'])
  const spinePts = [pelvis, v(J['spine-4']), v(J['spine-3']), v(J['spine-2']), v(J['spine-1']), neck, head]
  const spine = new THREE.CatmullRomCurve3(spinePts)
  const chestZ = -0.035

  const ribTop = J['spine-1'][1] + 0.07
  const lungY = ribTop - 0.1
  const gutTop = lungY - 0.15
  let heart: THREE.Mesh | null = null
  if (!real) {
    // ---- brain and eyes
    // Sits inside the skull: the head is about ±0.075 m wide and -0.155..+0.04 m deep between y 1.64 and 1.70
    organ('brain', [0, top.y - 0.069, head.z + 0.037], [0.056, 0.046, 0.07], SYSTEM_COLOR.brain, 4, 0.04)
    for (const s of ['l', 'r']) organ('eyes', J[`${s}-eye`], [0.012, 0.012, 0.012], SYSTEM_COLOR.eyes, 2)

    // ---- skeleton: vertebrae, ribs, sternum, clavicles, pelvis, limbs, hands, feet
    for (let i = 0; i <= 26; i++) {
      const p = spine.getPoint(i / 26)
      const m = new THREE.Mesh(new THREE.BoxGeometry(0.026, 0.011, 0.022), glowMaterial(SYSTEM_COLOR.skeleton, 0.8))
      m.position.copy(p)
      add(m, 'skeleton', 'bone')
    }
    for (let k = 0; k < 10; k++) {
      const y = ribTop - k * 0.026
      const a = 0.095 + 0.04 * Math.sin(((k + 1) / 11) * Math.PI * 0.85)
      const b = 0.085
      for (const s of [1, -1]) {
        const pts: THREE.Vector3[] = []
        for (let i = 0; i <= 10; i++) {
          const al = Math.PI - i * ((Math.PI - (k < 7 ? 0.32 : 0.75)) / 10)
          pts.push(new THREE.Vector3(s * a * Math.sin(al), y - 0.045 * (1 - Math.cos((i / 10) * Math.PI)) / 2, chestZ + b * Math.cos(al)))
        }
        tube(pts, 0.0034, 'skeleton', 'bone', SYSTEM_COLOR.skeleton)
      }
    }
    bone(new THREE.Vector3(0, ribTop - 0.01, chestZ + 0.08), new THREE.Vector3(0, ribTop - 0.19, chestZ + 0.075), 0.008)
    for (const s of ['l', 'r']) {
      const sh = v(J[`${s}-shoulder`]), el = v(J[`${s}-elbow`]), ha = v(J[`${s}-hand`])
      const up = v(J[`${s}-upper-leg`]), kn = v(J[`${s}-knee`]), an = v(J[`${s}-ankle`])
      bone(new THREE.Vector3(Math.sign(sh.x) * 0.02, ribTop + 0.005, chestZ + 0.06), sh, 0.006)
      bone(sh, el, 0.014)
      const off = new THREE.Vector3(0, 0, 0.008)
      bone(el.clone().add(off), ha.clone().add(off), 0.007)
      bone(el.clone().sub(off), ha.clone().sub(off), 0.006)
      bone(up, kn, 0.019)
      const kneeCap = new THREE.Mesh(new THREE.IcosahedronGeometry(0.018, 2), glowMaterial(SYSTEM_COLOR.skeleton, 0.8))
      kneeCap.position.copy(kn).add(new THREE.Vector3(0, 0, 0.04)); add(kneeCap, 'skeleton', 'bone')
      bone(kn, an, 0.014)
      bone(kn.clone().add(new THREE.Vector3(Math.sign(kn.x) * 0.022, 0, -0.01)), an.clone().add(new THREE.Vector3(Math.sign(an.x) * 0.02, 0.02, -0.01)), 0.006)
      bone(pelvis.clone().add(new THREE.Vector3(Math.sign(up.x) * 0.03, 0.03, -0.02)), up, 0.012)
      for (let f = 1; f <= 5; f++) {
        const chain = [ha, ...[1, 2, 3, 4].map(n => J[`${s}-finger-${f}-${n}`]).filter(Boolean).map(v)]
        for (let i = 0; i < chain.length - 1; i++) bone(chain[i], chain[i + 1], 0.0045)
        const toes = [1, 2, 3, 4].map(n => J[`${s}-toe-${f}-${n}`]).filter(Boolean).map(v)
        const tchain = [an, ...toes]
        for (let i = 0; i < tchain.length - 1; i++) bone(tchain[i], tchain[i + 1], 0.005)
      }
    }
    for (const s of [1, -1]) {
      const hip = new THREE.Mesh(new THREE.TorusGeometry(0.06, 0.007, 6, 28, Math.PI * 1.15), glowMaterial(SYSTEM_COLOR.skeleton, 0.75))
      hip.position.set(s * 0.065, pelvis.y + 0.05, pelvis.z + 0.02)
      hip.rotation.set(0.2, s * 0.9, s > 0 ? -0.2 : Math.PI + 0.2)
      add(hip, 'skeleton', 'bone')
    }
    centers.skeleton = new THREE.Vector3(0, 1.0, 0)

    // ---- thorax and abdomen
    organ('lungs', [0.068, lungY, chestZ - 0.01], [0.056, 0.105, 0.062], SYSTEM_COLOR.lungs, 3, 0.03)
    organ('lungs', [-0.07, lungY, chestZ - 0.01], [0.06, 0.105, 0.064], SYSTEM_COLOR.lungs, 3, 0.03)
    centers.lungs = new THREE.Vector3(0, lungY, chestZ)
    heart = organ('heart', [0.022, lungY - 0.035, chestZ + 0.025], [0.042, 0.05, 0.04], SYSTEM_COLOR.heart, 3, 0.05)
    heart.rotation.z = -0.5
    heart.userData.base = heart.scale.clone()
    organ('gut', [-0.05, gutTop + 0.02, chestZ], [0.085, 0.048, 0.06], '#ffb86b', 3, 0.03) // liver
    organ('gut', [0.055, gutTop, chestZ + 0.005], [0.048, 0.036, 0.04], SYSTEM_COLOR.gut, 3, 0.04) // stomach
    organ('immune', [0.1, gutTop + 0.005, chestZ - 0.05], [0.022, 0.04, 0.024], SYSTEM_COLOR.immune, 2) // spleen
    for (const s of [1, -1]) organ('kidneys', [s * 0.052, gutTop - 0.04, -0.115], [0.022, 0.04, 0.02], SYSTEM_COLOR.kidneys, 2)
    organ('kidneys', [0, pelvis.y + 0.005, chestZ + 0.02], [0.026, 0.022, 0.022], SYSTEM_COLOR.kidneys, 2) // bladder
    const coil: THREE.Vector3[] = []
    for (let i = 0; i <= 90; i++) {
      const t = i / 90
      coil.push(new THREE.Vector3(0.075 * Math.sin(t * Math.PI * 7) * (0.55 + 0.45 * Math.sin(t * Math.PI)),
        gutTop - 0.06 - t * 0.12 + 0.012 * Math.sin(t * 40), chestZ + 0.03 + 0.02 * Math.cos(t * Math.PI * 7)))
    }
    tube(coil, 0.009, 'gut', 'vessel', '#7cf3ff', 0.15, 0.85)
    centers.gut = new THREE.Vector3(0, gutTop - 0.08, chestZ)
    centers.kidneys = new THREE.Vector3(0.052, gutTop - 0.04, -0.115)
    centers.immune = new THREE.Vector3(0.1, gutTop, chestZ - 0.05)
  }

  // ---- real meshes: same materials, same tags, same centres as the procedural parts
  let hc = heart ? heart.position.clone() : new THREE.Vector3()
  let aortaTop = new THREE.Vector3(0, hc.y + 0.06, -0.06), aortaBottom = new THREE.Vector3(0, pelvis.y + 0.04, -0.06)
  let canal: THREE.Vector3[] = []
  let brainBase = new THREE.Vector3(0, top.y - 0.08, head.z + 0.01)
  if (real) {
    const boxes: Record<string, THREE.Box3> = {}
    const end = (g: THREE.BufferGeometry, upper: boolean) => {
      const p = g.getAttribute('position') as THREE.BufferAttribute, bb = g.boundingBox!
      const y0 = upper ? bb.max.y : bb.min.y, c = new THREE.Vector3(); let n = 0
      for (let i = 0; i < p.count; i++) if (Math.abs(p.getY(i) - y0) < 0.012) { c.add(new THREE.Vector3(p.getX(i), p.getY(i), p.getZ(i))); n++ }
      return c.divideScalar(Math.max(1, n))
    }
    for (const r of real.meshes) {
      const flow = FLOW[r.name]
      const mat = flow ? flowMaterial(flow.color, flow.speed, flow.opacity) : glowMaterial(r.color ?? SYSTEM_COLOR[r.system], r.kind === 'bone' ? 0.75 : 0.9)
      r.geometry.computeBoundingBox()
      boxes[r.name] = r.geometry.boundingBox!.clone()
      if (r.name === 'aorta') { aortaTop = end(r.geometry, true); aortaBottom = end(r.geometry, false) }
      const m = new THREE.Mesh(r.geometry, mat)
      if (r.name === 'heart') { // the beat scales it about its own centre
        const c = boxes.heart.getCenter(new THREE.Vector3())
        r.geometry.translate(-c.x, -c.y, -c.z); m.position.copy(c); hc = c
      }
      add(m, r.system, r.kind)
      m.userData.base = m.scale.clone()
      m.userData.glow = r.glow
    }
    const mid = (...names: string[]) => names.reduce((b, n) => b.union(boxes[n]), new THREE.Box3()).getCenter(new THREE.Vector3())
    centers.skeleton = new THREE.Vector3(0, 1.0, 0)
    centers.brain = mid('brain')
    centers.eyes = mid('eye_left', 'eye_right')
    centers.heart = hc.clone()
    centers.lungs = mid('lung_left', 'lung_right')
    centers.gut = mid('liver', 'stomach', 'small_intestine', 'large_intestine')
    centers.kidneys = mid('kidney_left', 'kidney_right')
    centers.immune = mid('spleen')
    canal = real.spine.map(p => v(p))
    brainBase = new THREE.Vector3(boxes.brain.getCenter(new THREE.Vector3()).x, boxes.brain.min.y + 0.02, boxes.brain.getCenter(new THREE.Vector3()).z - 0.03)
  }
  const canalAt = (y: number, fallback: Vec) => canal.length ? canal.reduce((b, p) => Math.abs(p.y - y) < Math.abs(b.y - y) ? p : b).clone() : v(fallback)

  // ---- vessels: aorta down to the legs, carotids to the head (the aorta itself is a real mesh when we have one)
  if (!real) {
    const aortaPts = [hc, hc.clone().add(new THREE.Vector3(0, 0.07, -0.01)), new THREE.Vector3(0, hc.y + 0.06, -0.07), new THREE.Vector3(0, hc.y - 0.05, -0.085),
      new THREE.Vector3(0, gutTop - 0.08, -0.07), new THREE.Vector3(0, pelvis.y + 0.04, -0.06)]
    tube(aortaPts, 0.006, 'heart', 'vessel', '#ff4f8e', 0.7)
  }
  // drawn only when the model has no real arteries of the neck and limbs
  const realArteries = !!real?.meshes.some(m => m.name.startsWith('arteries_'))
  for (const s of realArteries ? [] : ['l', 'r']) {
    const sg = s === 'l' ? 1 : -1
    tube([aortaBottom.clone(), v(J[`${s}-upper-leg`]).add(new THREE.Vector3(0, 0, 0.03)), v(J[`${s}-knee`]).add(new THREE.Vector3(0, 0, -0.01)), v(J[`${s}-ankle`])], 0.0045, 'heart', 'vessel', '#ff4f8e', 0.7)
    tube([aortaTop.clone(), new THREE.Vector3(sg * 0.025, neck.y, 0), new THREE.Vector3(sg * 0.03, head.y + 0.02, 0.0)], 0.004, 'heart', 'vessel', '#ff4f8e', 0.7)
    tube([new THREE.Vector3(sg * 0.03, aortaTop.y + 0.02, aortaTop.z + 0.02), v(J[`${s}-shoulder`]), v(J[`${s}-elbow`]).add(new THREE.Vector3(0, 0, 0.012)), v(J[`${s}-hand`])], 0.0038, 'heart', 'vessel', '#ff4f8e', 0.7)
  }
  centers.heart = hc.clone()

  // ---- nervous system: cord and limb nerves (lit by the Mental lens)
  const cord = real ? [...canal, brainBase] : [...spinePts.slice(0, 6), new THREE.Vector3(0, top.y - 0.08, head.z + 0.01)]
  tube(cord.map(p => real ? p : p.clone().add(new THREE.Vector3(0, 0, -0.012))), 0.0045, 'brain', 'nerve', '#c9a6ff', 0.6, 0.35)
  for (const s of ['l', 'r']) {
    tube([canalAt(J['spine-1'][1], J['spine-1']), v(J[`${s}-shoulder`]), v(J[`${s}-elbow`]).add(new THREE.Vector3(0, 0, -0.012)), v(J[`${s}-hand`]), v(J[`${s}-finger-3-4`])], 0.0028, 'brain', 'nerve', '#c9a6ff', 0.6, 0.35)
    tube([canalAt(J['spine-4'][1], J['spine-4']), v(J[`${s}-upper-leg`]).add(new THREE.Vector3(0, 0, -0.02)), v(J[`${s}-knee`]).add(new THREE.Vector3(0, 0, -0.03)), v(J[`${s}-ankle`]), v(J[`${s}-toe-3-3`] ?? J[`${s}-toe-1-3`])], 0.003, 'brain', 'nerve', '#c9a6ff', 0.6, 0.35)
  }
  if (!real) centers.brain = new THREE.Vector3(0, top.y - 0.069, head.z + 0.037)
  centers.eyes ??= v(J['l-eye']).add(v(J['r-eye'])).multiplyScalar(0.5)
  centers.muscles = v(J['l-knee']).add(new THREE.Vector3(0, 0.2, 0))
  centers.skin = new THREE.Vector3(0, lungY - 0.05, 0.05)

  return { group, parts, centers }
}
