import { Navigate, Route, Routes } from 'react-router-dom'
import Shell from './components/Shell'
import About from './pages/About'
import Astronaut from './pages/Astronaut'
import Crew from './pages/Crew'
import Goals from './pages/Goals'
import Intro from './pages/Intro'
import Me from './pages/Me'
import Medical from './pages/Medical'
import MissionPlan from './pages/MissionPlan'
import Ranking from './pages/Ranking'
import Setup from './pages/Setup'

function seenIntro(): boolean {
  try { return sessionStorage.getItem('canary.intro') === '1' } catch { return true }
}

export default function App() {
  return (
    <Routes>
      <Route path="/welcome" element={<Intro />} />
      <Route path="/setup" element={<Setup />} />
      <Route element={<Shell />}>
        <Route path="/today" element={<Me />} />
        <Route path="/me" element={<Navigate to="/today" replace />} />
        <Route path="/ranking" element={<Ranking />} />
        <Route path="/crew" element={<Crew />} />
        <Route path="/crew/:id" element={<Astronaut />} />
        <Route path="/goals" element={<Goals />} />
        <Route path="/plan" element={<MissionPlan />} />
        <Route path="/space-weather" element={<Navigate to="/crew" replace />} />
        <Route path="/link" element={<Navigate to="/crew" replace />} />
        <Route path="/mission" element={<Navigate to="/plan" replace />} />
        <Route path="/medical" element={<Medical />} />
        <Route path="/about" element={<About />} />
      </Route>
      <Route path="*" element={<Navigate to={seenIntro() ? '/crew' : '/welcome'} replace />} />
    </Routes>
  )
}
