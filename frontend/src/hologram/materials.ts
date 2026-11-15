// Shaders for the hologram. Everything is additive and view-dependent (fresnel), so the body reads
// as light, not as a solid: the skin is an iridescent shell, organs and bones glow inside it.
import * as THREE from 'three'

export const STATUS_COLOR = [new THREE.Color('#3ddc97'), new THREE.Color('#ffb547'), new THREE.Color('#ff4d5e')]
/** A system with nothing measured: neutral grey, never a status colour. */
export const NO_DATA_COLOR = new THREE.Color('#7b8490')

const REVEAL = /* glsl */ `
  float reveal(float y, float r) { return smoothstep(r, r - 0.06, y); }
  float revealEdge(float y, float r) { return exp(-pow((y - r) * 40.0, 2.0)); }
`

export function bodyMaterial() {
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.FrontSide,
    uniforms: {
      uTime: { value: 0 }, uLens: { value: 0 }, uReveal: { value: 0 }, uDim: { value: 1 }, uRad: { value: 0 },
      uBoost: { value: new Array(6).fill(0) },
      uTint: { value: Array.from({ length: 6 }, () => new THREE.Vector4(0, 0, 0, 0)) },
    },
    vertexShader: /* glsl */ `
      attribute float _region;
      varying vec3 vN; varying vec3 vV; varying vec3 vP; varying float vR; varying float vY;
      void main() {
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vec4 mv = viewMatrix * wp;
        vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz);
        vP = position; vR = _region; vY = wp.y;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      uniform float uTime, uLens, uReveal, uDim, uRad; uniform float uBoost[6]; uniform vec4 uTint[6];
      varying vec3 vN; varying vec3 vV; varying vec3 vP; varying float vR; varying float vY;
      ${REVEAL}
      vec3 spectrum(float t) {
        t = fract(t);
        vec3 c0 = vec3(0.37, 0.95, 1.0), c1 = vec3(0.36, 0.52, 1.0), c2 = vec3(0.66, 0.48, 1.0);
        vec3 c3 = vec3(1.0, 0.38, 0.83), c4 = vec3(1.0, 0.80, 0.36);
        if (t < 0.25) return mix(c0, c1, t / 0.25);
        if (t < 0.5) return mix(c1, c2, (t - 0.25) / 0.25);
        if (t < 0.75) return mix(c2, c3, (t - 0.5) / 0.25);
        return mix(c3, c4, (t - 0.75) / 0.25);
      }
      void main() {
        int r = int(vR + 0.5);
        float f = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 2.1);
        float fiber = 0.7 + 0.3 * sin(vP.y * 260.0 + sin(vP.x * 70.0 + vP.z * 40.0) * 2.5);
        float t = f * 0.55 + vP.y * 0.6 + 0.22 * sin(vP.x * 11.0 + vP.y * 4.0 + vP.z * 6.0 + uTime * 0.25);
        vec3 col = spectrum(t) * (0.05 + 1.25 * f) * fiber;
        // a quiet, cool silhouette: the colours inside belong to the organs, so the shell stays nearly neutral
        col = mix(col, vec3(dot(col, vec3(0.333))) * vec3(0.72, 0.84, 1.0), 0.65) * 0.75;
        float scan = exp(-pow((vY - mod(uTime * 0.42, 2.6) + 0.4) * 22.0, 2.0));
        col += vec3(0.37, 0.95, 1.0) * scan * 0.35;
        float b = 0.0; vec4 tint = vec4(0.0);
        for (int i = 0; i < 6; i++) { if (i == r) { b = uBoost[i]; tint = uTint[i]; } }
        col += vec3(0.55, 0.95, 1.0) * b * (0.18 + 0.9 * f);
        float pulse = 0.65 + 0.35 * sin(uTime * 4.0);
        col = mix(col, tint.rgb * (0.22 + 1.4 * f), tint.a * pulse);
        vec3 calm = vec3(0.62, 0.48, 1.0) * (0.03 + 0.55 * f);
        col = mix(col, calm, uLens * 0.75 * (1.0 - tint.a));
        // Radiation exposure: the whole body, scanned by a band that sweeps from the feet to the head and back
        vec3 rc = vec3(0.78, 1.0, 0.18);
        float sweep = 0.5 - 0.5 * cos(uTime * 0.9);
        float band = exp(-pow((vY - sweep * 1.8) * 16.0, 2.0));
        float trail = exp(-pow((vY - sweep * 1.8) * 4.0, 2.0)) * 0.35;
        float grain = 0.75 + 0.25 * sin(vY * 420.0);
        vec3 rad = rc * (0.08 + 0.8 * f) + rc * (band * 2.2 + trail) * grain;
        col = mix(col, rad, uRad);
        float a = clamp(0.1 + 0.9 * f + uRad * (band + trail), 0.0, 1.0) * uDim * 0.85;
        col += vec3(0.6, 1.0, 1.0) * revealEdge(vY, uReveal) * 1.4;
        gl_FragColor = vec4(col * a * reveal(vY, uReveal), 1.0);
      }`,
  })
}

/** Inner structures: a fresnel glow in one colour that can be boosted (hover), tinted (status) or dimmed (lens). */
export function glowMaterial(color: string, opacity = 1) {
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: {
      uColor: { value: new THREE.Color(color) }, uBase: { value: new THREE.Color(color) },
      uOpacity: { value: opacity }, uBoost: { value: 0 }, uTime: { value: 0 }, uPulse: { value: 0 }, uReveal: { value: 0 },
    },
    vertexShader: /* glsl */ `
      varying vec3 vN; varying vec3 vV; varying float vY;
      void main() {
        vec4 wp = modelMatrix * vec4(position, 1.0); vec4 mv = viewMatrix * wp;
        vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz); vY = wp.y;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor; uniform float uOpacity, uBoost, uTime, uPulse, uReveal;
      varying vec3 vN; varying vec3 vV; varying float vY;
      ${REVEAL}
      void main() {
        // A crisp rim and a thin fill: many real surfaces overlap, and a thick fill sums into a milky haze.
        float e = 1.0 - abs(dot(normalize(vN), normalize(vV)));
        float f = pow(e, 2.2) + 0.35 * smoothstep(0.82, 0.97, e);
        float p = 1.0 + uPulse * (0.45 * sin(uTime * 5.0));
        vec3 col = uColor * (0.07 + 0.75 * f) * p * (1.0 + uBoost * 1.8);
        gl_FragColor = vec4(col * uOpacity * reveal(vY, uReveal), 1.0);
      }`,
  })
}

/** Nerves and vessels: light travelling along the tube (uv.x runs along its length). */
export function flowMaterial(color: string, speed = 0.5, opacity = 1) {
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uColor: { value: new THREE.Color(color) }, uBase: { value: new THREE.Color(color) }, uOpacity: { value: opacity },
      uTime: { value: 0 }, uSpeed: { value: speed }, uBoost: { value: 0 }, uPulse: { value: 0 }, uReveal: { value: 0 } },
    vertexShader: /* glsl */ `
      varying vec2 vUv; varying float vY;
      void main() { vUv = uv; vec4 wp = modelMatrix * vec4(position, 1.0); vY = wp.y; gl_Position = projectionMatrix * viewMatrix * wp; }`,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor; uniform float uOpacity, uTime, uSpeed, uBoost, uReveal;
      varying vec2 vUv; varying float vY;
      ${REVEAL}
      void main() {
        float pulse = pow(fract(vUv.x * 4.0 - uTime * uSpeed), 10.0);
        vec3 col = uColor * (0.18 + 1.1 * pulse) * (1.0 + uBoost * 1.5);
        gl_FragColor = vec4(col * uOpacity * reveal(vY, uReveal), 1.0);
      }`,
  })
}

/** Muscle layer: fibres running along each limb segment (aFiber.x is the angle around the bone, .y the position along
 *  it, .z how many fibres go round), bellies in the middle, paler tendons at the ends, a slow contraction wave. */
export function fibreMaterial(color: string) {
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uColor: { value: new THREE.Color(color) }, uBase: { value: new THREE.Color(color) }, uOpacity: { value: 0 },
      uBoost: { value: 0 }, uTime: { value: 0 }, uPulse: { value: 0 }, uReveal: { value: 0 } },
    vertexShader: /* glsl */ `
      attribute vec3 aFiber;
      varying vec3 vN; varying vec3 vV; varying vec3 vF; varying float vY;
      void main() {
        vec4 wp = modelMatrix * vec4(position, 1.0); vec4 mv = viewMatrix * wp;
        vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz); vF = aFiber; vY = wp.y;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor; uniform float uOpacity, uBoost, uTime, uPulse, uReveal;
      varying vec3 vN; varying vec3 vV; varying vec3 vF; varying float vY;
      ${REVEAL}
      void main() {
        float e = 1.0 - abs(dot(normalize(vN), normalize(vV)));
        float f = pow(e, 1.8);
        float t = clamp(vF.y, 0.0, 1.0);
        float s = abs(sin(vF.x * vF.z * 0.5 + 0.35 * sin(t * 9.0 + vF.x * 3.0)));
        float line = smoothstep(0.86, 1.0, s);
        float belly = smoothstep(-0.04, 0.05, t) * smoothstep(1.0, 0.88, t);   // tendons at the far end of a segment
        float wave = 0.75 + 0.25 * sin(t * 12.0 - uTime * 2.2);
        float p = 1.0 + uPulse * (0.45 * sin(uTime * 5.0));
        vec3 col = uColor * (0.05 + 0.45 * f + line * (0.35 + 0.55 * belly) * wave);
        col = mix(col, vec3(1.0, 0.93, 0.85) * (0.08 + 0.5 * f), (1.0 - belly) * 0.55);
        col *= p * (1.0 + uBoost * 0.8);
        gl_FragColor = vec4(col * uOpacity * reveal(vY, uReveal), 1.0);
      }`,
  })
}
