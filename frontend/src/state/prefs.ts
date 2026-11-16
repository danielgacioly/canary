// Preferences for this device: appearance, accessibility, Guided Response voice, demo bar.
// They live in localStorage on purpose: they belong to the terminal, not to a person.

export interface Prefs {
  theme: 'dark' | 'light' | 'system'
  largeText: boolean
  reduceMotion: boolean
  highContrast: boolean
  voice: boolean
  storyBar: boolean
}

export const DEFAULT_PREFS: Prefs = { theme: 'light', largeText: false, reduceMotion: false, highContrast: true, voice: false, storyBar: true }

// Bump when the defaults change. A stored version older than this gets the new theme and contrast defaults once;
// after that, whatever the person picks in Settings is kept.
export const PREFS_VERSION = 2
const PREFS_VERSION_KEY = 'canary.prefs.v'

export function loadPrefs(): Prefs {
  let raw: Partial<Prefs> = {}
  let version = 0
  try {
    raw = JSON.parse(localStorage.getItem('canary.prefs') || '{}')
    version = Number(localStorage.getItem(PREFS_VERSION_KEY)) || 0
    // the earlier light-mode toggle stored only the theme
    if (!raw.theme && localStorage.getItem('canary.theme') === 'light') raw.theme = 'light'
  } catch {
    raw = {}
  }
  const p: Prefs = { ...DEFAULT_PREFS, ...raw }
  if (version < PREFS_VERSION) {
    p.theme = DEFAULT_PREFS.theme
    p.highContrast = DEFAULT_PREFS.highContrast
    savePrefs(p)
    try { localStorage.setItem(PREFS_VERSION_KEY, String(PREFS_VERSION)) } catch { /* storage blocked */ }
  }
  return p
}

export function savePrefs(p: Prefs) {
  try { localStorage.setItem('canary.prefs', JSON.stringify(p)) } catch { /* storage blocked */ }
}

const systemDark = () => typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches

/** Mirror the preferences onto <html> so the stylesheet can follow them. */
export function applyPrefs(p: Prefs) {
  const root = document.documentElement
  const light = p.theme === 'light' || (p.theme === 'system' && !systemDark())
  if (light) root.dataset.theme = 'light'
  else delete root.dataset.theme
  root.dataset.text = p.largeText ? 'large' : ''
  root.dataset.motion = p.reduceMotion ? 'reduce' : ''
  root.dataset.contrast = p.highContrast ? 'high' : ''
}
