// Guided Response voice: a clear, standard radio-style English voice, chosen explicitly. The browser's default voice
// follows the device language and can read English with a foreign accent, so no English voice means no speech.
import { useEffect, useState } from 'react'

/** Novelty and character voices that ship with macOS; never used for an emergency. */
const NOVELTY = /^(Albert|Bad News|Bahh|Bells|Boing|Bubbles|Cellos|Good News|Jester|Organ|Superstar|Trinoids|Whisper|Wobble|Zarvox|Junior|Ralph|Fred|Eddy|Flo|Grandma|Grandpa|Reed|Rocko|Sandy|Shelley)\b/i
// Neural and downloaded voices sound human; they win over the language order. Then standard, calm system voices.
const QUALITY: [RegExp, number][] = [[/natural|neural|siri/i, 24], [/premium/i, 22], [/enhanced/i, 18],
  [/^(Samantha|Alex|Ava|Allison|Susan|Zoe|Serena|Karen|Moira|Evan|Nathan|Tom|Daniel)\b/i, 6],
  [/microsoft (aria|jenny|guy)/i, 6], [/microsoft/i, 4], [/google/i, 2]]
// A voice that runs on the device. Chrome's network voices ("Google US English") fall back to the system default
// voice when Google cannot be reached, and on a Portuguese system that reads the English text with a Portuguese voice.
const LOCAL_BONUS = 40

/** The best English voice of the list, or null. A voice on the device first, then en-US, en-GB, any other English. */
export function pickEnglishVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const score = (v: SpeechSynthesisVoice): number => {
    const lang = v.lang.replace('_', '-').toLowerCase()
    let s = lang === 'en-us' ? 30 : lang === 'en-gb' ? 20 : 10
    if (v.localService) s += LOCAL_BONUS
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
        const checked = voice !== null || list.length > 0 || final
        // Keep the same object while the choice is the same voice: a late `voiceschanged` must not restart speech.
        setState(prev => (prev.voice?.voiceURI === voice?.voiceURI && prev.checked === checked ? prev : { voice, checked }))
      } catch { setState(prev => (prev.voice === null && prev.checked ? prev : { voice: null, checked: true })) }
    }
    const onChange = () => read(false)
    try { speechSynthesis.addEventListener('voiceschanged', onChange) } catch { /* no speech */ }
    read(false)
    timer = window.setTimeout(() => read(true), 2000)  // a device with no voices never fires the event
    return () => { window.clearTimeout(timer); try { speechSynthesis.removeEventListener('voiceschanged', onChange) } catch { /* no speech */ } }
  }, [])
  return state
}

/** What is read for a screen: exactly the lines it shows, each ending as a sentence. Markup, parentheses and emoji are
 *  dropped, symbols spoken. */
export function screenSpeech(parts: (string | null | undefined)[]): string {
  return parts.filter((p): p is string => !!p).map(cleanSpeech).filter(Boolean)
    .map(s => (/[.?!]$/.test(s) ? s : `${s}.`)).join(' ')
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

/** A soft two-note chime before a step (a falling fifth, slow attack, low volume): it asks for attention without
 *  alarm. No audio file. Returns its length in ms. */
export function chirp(): number {
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctx) return 0
    audio = audio ?? new Ctx()
    if (audio.state === 'suspended') void audio.resume()
    const t0 = audio.currentTime + 0.02
    ;[[784, 0], [523, 0.22]].forEach(([hz, at]) => {
      const osc = audio!.createOscillator(), gain = audio!.createGain()
      osc.type = 'sine'; osc.frequency.value = hz
      gain.gain.setValueAtTime(0.0001, t0 + at)
      gain.gain.exponentialRampToValueAtTime(0.06, t0 + at + 0.04)
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + at + 0.5)
      osc.connect(gain).connect(audio!.destination)
      osc.start(t0 + at); osc.stop(t0 + at + 0.52)
    })
    return 700
  } catch { return 0 }
}

/** Chime, then read `text` with `voice`, one sentence at a time with a short breath between them, a little slower
 *  than normal speech: steady and calm, not robotic. Returns a function that cancels everything. */
export function speakWithChirp(text: string, voice: SpeechSynthesisVoice): () => void {
  let timer: number | undefined
  let stopped = false
  const sentences = text.match(/[^.?!]+[.?!]*/g)?.map(s => s.trim()).filter(Boolean) ?? [text]
  const say = (k: number) => {
    if (stopped || k >= sentences.length) return
    try {
      const u = new SpeechSynthesisUtterance(sentences[k])
      u.voice = voice; u.lang = /^en[-_]us$/i.test(voice.lang) ? 'en-US' : voice.lang.replace('_', '-'); u.rate = 0.9; u.pitch = 1.0; u.volume = 0.95
      u.onend = () => { timer = window.setTimeout(() => say(k + 1), k === 0 ? 450 : 320) }
      speechSynthesis.speak(u)
    } catch { /* no speech */ }
  }
  try {
    speechSynthesis.cancel()
    speechSynthesis.resume()  // Chrome can stay paused after cancel(); every later utterance would then wait silently
    timer = window.setTimeout(() => say(0), chirp())
  } catch { /* no speech */ }
  return () => { stopped = true; window.clearTimeout(timer); try { speechSynthesis.cancel() } catch { /* no speech */ } }
}
