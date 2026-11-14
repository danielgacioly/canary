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

export const DEFAULT_PREFS: Prefs = { theme: 'dark', largeText: false, reduceMotion: false, highContrast: false, voice: false, storyBar: true }

export function loadPrefs(): Prefs {
  try {
    const raw = JSON.parse(localStorage.getItem('canary.prefs') || '{}')
    // the earlier light-mode toggle stored only the theme
    if (!raw.theme && localStorage.getItem('canary.theme') === 'light') raw.theme = 'light'
    return { ...DEFAULT_PREFS, ...raw }
  } catch {
    return { ...DEFAULT_PREFS }
  }
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
