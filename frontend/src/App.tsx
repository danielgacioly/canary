import { Navigate, Route, Routes } from 'react-router-dom'
import Shell from './components/Shell'
import Tour from './components/Tour'
import OfflineBanner from './components/OfflineBanner'
import About from './pages/About'
import Astronaut from './pages/Astronaut'
import Crew from './pages/Crew'
import Intro from './pages/Intro'
import MySpace from './pages/MySpace'
import Control from './pages/Control'
import Medical from './pages/Medical'
import MissionInfo from './pages/MissionInfo'
import MissionPlan from './pages/MissionPlan'
import Protocols from './pages/Protocols'
import Ranking from './pages/Ranking'
import Settings from './pages/Settings'
import Tests from './pages/Tests'

function seenIntro(): boolean {
  try { return sessionStorage.getItem('canary.intro') === '1' } catch { return true }
}

export default function App() {
  return (
    <>
    <OfflineBanner />
    <Tour />
    <Routes>
      <Route path="/welcome" element={<Intro />} />
      <Route path="/control" element={<Control />} />
      <Route element={<Shell />}>
        <Route path="/me" element={<MySpace />} />
        <Route path="/me/:tab" element={<MySpace />} />
        <Route path="/today" element={<Navigate to="/me" replace />} />
        <Route path="/goals" element={<Navigate to="/me/goals" replace />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/tests" element={<Tests />} />
        <Route path="/ranking" element={<Ranking />} />
        <Route path="/crew" element={<Crew />} />
        <Route path="/crew/:id" element={<Astronaut />} />
        <Route path="/protocols" element={<Protocols />} />
        <Route path="/protocols/:id" element={<Protocols />} />
        <Route path="/plan" element={<MissionPlan />} />
        <Route path="/space-weather" element={<Navigate to="/crew" replace />} />
        <Route path="/link" element={<Navigate to="/crew" replace />} />
        <Route path="/mission" element={<MissionInfo />} />
        <Route path="/medical" element={<Medical />} />
        <Route path="/about" element={<About />} />
      </Route>
      <Route path="*" element={<Navigate to={seenIntro() ? '/crew' : '/welcome'} replace />} />
    </Routes>
    </>
  )
}
