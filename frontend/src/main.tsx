import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { SessionProvider } from './state/session'
import './styles/app.css'

import { applyPrefs, loadPrefs } from './state/prefs'

// Appearance before first paint, so a light-mode terminal never flashes dark.
applyPrefs(loadPrefs())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <SessionProvider>
        <App />
      </SessionProvider>
    </BrowserRouter>
  </StrictMode>,
)
