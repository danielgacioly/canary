import { Navigate, Route, Routes } from 'react-router-dom'
import Shell from './components/Shell'
import About from './pages/About'
import Astronaut from './pages/Astronaut'
import Crew from './pages/Crew'
import Goals from './pages/Goals'
import Intro from './pages/Intro'
import Me from './pages/Me'
import Medical from './pages/Medical'
import Mission from './pages/Mission'
import { useSession } from './state/session'

export default function App() {
  const { me } = useSession()
  return (
    <Routes>
      <Route path="/welcome" element={<Intro />} />
      <Route element={<Shell />}>
        <Route path="/today" element={<Me />} />
        <Route path="/me" element={<Navigate to="/today" replace />} />
        <Route path="/ranking" element={<Navigate to="/goals?tab=ranking" replace />} />
        <Route path="/crew" element={<Crew />} />
        <Route path="/crew/:id" element={<Astronaut />} />
        <Route path="/goals" element={<Goals />} />
        <Route path="/mission" element={<Mission />} />
        <Route path="/medical" element={<Medical />} />
        <Route path="/about" element={<About />} />
      </Route>
      <Route path="*" element={<Navigate to={me ? '/today' : '/welcome'} replace />} />
    </Routes>
  )
}
