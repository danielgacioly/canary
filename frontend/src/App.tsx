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
import Ranking from './pages/Ranking'
import { useSession } from './state/session'

export default function App() {
  const { me } = useSession()
  return (
    <Routes>
      <Route path="/welcome" element={<Intro />} />
      <Route element={<Shell />}>
        <Route path="/me" element={<Me />} />
        <Route path="/crew" element={<Crew />} />
        <Route path="/crew/:id" element={<Astronaut />} />
        <Route path="/goals" element={<Goals />} />
        <Route path="/ranking" element={<Ranking />} />
        <Route path="/mission" element={<Mission />} />
        <Route path="/medical" element={<Medical />} />
        <Route path="/about" element={<About />} />
      </Route>
      <Route path="*" element={<Navigate to={me ? '/me' : '/welcome'} replace />} />
    </Routes>
  )
}
