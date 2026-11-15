// Guided Response voice: a clear, standard radio-style English voice, chosen explicitly. The browser's default voice
// follows the device language and can read English with a foreign accent, so no English voice means no speech.
import { useEffect, useState } from 'react'

/** Novelty voices that ship with macOS; never used for an emergency. */
const NOVELTY = /^(Albert|Bad News|Bahh|Bells|Boing|Bubbles|Cellos|Good News|Jester|Organ|Superstar|Trinoids|Whisper|Wobble|Zarvox|Junior|Ralph|Fred)\b/i
const QUALITY: [RegExp, number][] = [[/natural/i, 9], [/premium/i, 8], [/enhanced/i, 8], [/google/i, 6], [/microsoft/i, 6], [/^(Samantha|Alex|Daniel|Ava|Allison|Tom|Susan)\b/i, 3]]

/** The best English voice of the list, or null. en-US first, then en-GB, then any other English. */
export function pickEnglishVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const score = (v: SpeechSynthesisVoice): number => {
    const lang = v.lang.replace('_', '-').toLowerCase()
    let s = lang === 'en-us' ? 30 : lang === 'en-gb' ? 20 : 10
    for (const [re, w] of QUALITY) if (re.test(v.name)) s += w
    return s
  }
  const english = voices.filter(v => /^en([-_]|$)/i.test(v.lang) && !NOVELTY.test(v.name))
  return english.sort((a, b) => score(b) - score(a))[0] ?? null
}

/** The chosen voice. `checked` turns true once the device has listed its voices (some browsers list them late). */
export function useEnglishVoice(): { voice: SpeechSynthesisVoice | null; checked: boolean } {
  const [state, setState] = useState<{ voice: SpeechSynthesisVoice | null; checked: boolean }>({ voice: null, checked: false })
  useEffect(() => {
    let timer: number | undefined
    const read = (final: boolean) => {
      try {
        const list = speechSynthesis.getVoices()
        const voice = pickEnglishVoice(list)
        setState({ voice, checked: voice !== null || list.length > 0 || final })
      } catch { setState({ voice: null, checked: true }) }
    }
    const onChange = () => read(false)
    try { speechSynthesis.addEventListener('voiceschanged', onChange) } catch { /* no speech */ }
    read(false)
    timer = window.setTimeout(() => read(true), 2000)  // a device with no voices never fires the event
    return () => { window.clearTimeout(timer); try { speechSynthesis.removeEventListener('voiceschanged', onChange) } catch { /* no speech */ } }
  }, [])
  return state
}

/** What is read for a step: "Step 2 of 7. Check for a pulse." Markup, parentheses and emoji are dropped, symbols spoken. */
export function stepSpeech(i: number, n: number, parts: (string | null | undefined)[]): string {
  const sentences = parts.filter((p): p is string => !!p).map(cleanSpeech).filter(Boolean)
    .map(s => (/[.?!]$/.test(s) ? s : `${s}.`))
  return [`Step ${i + 1} of ${n}.`, ...sentences].join(' ')
}

export function cleanSpeech(text: string): string {
  return text
    .replace(/<[^>]*>/g, ' ')
    .replace(/\([^)]*\)/g, ' ')
    .replace(/[\p{Extended_Pictographic}️‍]/gu, ' ')
    .replace(/[*_`#~]/g, '')
    .replace(/°\s*C\b/g, ' degrees Celsius').replace(/°\s*F\b/g, ' degrees Fahrenheit').replace(/°/g, ' degrees')
    .replace(/(\d)\s*%/g, '$1 percent').replace(/%/g, ' percent')
    .replace(/\s*&\s*/g, ' and ').replace(/\s*\+\s*/g, ' plus ')
    .replace(/(\d)\s*\/\s*min\b/g, '$1 per minute').replace(/(\d)\s*L\b/g, '$1 liters')
    .replace(/\s+([,.?!])/g, '$1').replace(/\s+/g, ' ').trim()
}

let audio: AudioContext | null = null

/** A short two-tone radio chirp before a step. No audio file: two sine beeps. Resolves with its length in ms. */
export function chirp(): number {
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctx) return 0
    audio = audio ?? new Ctx()
    if (audio.state === 'suspended') void audio.resume()
    const t0 = audio.currentTime + 0.02
    ;[[1000, 0], [1500, 0.09]].forEach(([hz, at]) => {
      const osc = audio!.createOscillator(), gain = audio!.createGain()
      osc.type = 'sine'; osc.frequency.value = hz
      gain.gain.setValueAtTime(0.0001, t0 + at)
      gain.gain.exponentialRampToValueAtTime(0.14, t0 + at + 0.01)
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + at + 0.08)
      osc.connect(gain).connect(audio!.destination)
      osc.start(t0 + at); osc.stop(t0 + at + 0.09)
    })
    return 260
  } catch { return 0 }
}

/** Chirp, then read `text` with `voice`. Returns a function that cancels both. */
export function speakWithChirp(text: string, voice: SpeechSynthesisVoice): () => void {
  let timer: number | undefined
  try {
    speechSynthesis.cancel()
    const wait = chirp()
    timer = window.setTimeout(() => {
      try {
        const u = new SpeechSynthesisUtterance(text)
        u.voice = voice; u.lang = voice.lang; u.rate = 1.0; u.pitch = 0.9; u.volume = 1
        speechSynthesis.speak(u)
      } catch { /* no speech */ }
    }, wait)
  } catch { /* no speech */ }
  return () => { window.clearTimeout(timer); try { speechSynthesis.cancel() } catch { /* no speech */ } }
}
