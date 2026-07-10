import { Route, Routes } from 'react-router'

import HomePage from '@/pages/HomePage'
import StudyPage from '@/pages/StudyPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/study/:documentId" element={<StudyPage />} />
    </Routes>
  )
}
