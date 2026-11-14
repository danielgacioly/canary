import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { SessionProvider } from './state/session'
import './styles/app.css'

// Theme before first paint: dark by default, light when chosen on this device.
try { if (localStorage.getItem('canary.theme') === 'light') document.documentElement.dataset.theme = 'light' } catch { /* storage blocked */ }

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <SessionProvider>
        <App />
      </SessionProvider>
    </BrowserRouter>
  </StrictMode>,
)
