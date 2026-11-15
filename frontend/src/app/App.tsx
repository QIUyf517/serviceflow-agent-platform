import { QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { createQueryClient } from './queryClient'
import { AppFrame } from '../components/AppFrame'
import { AdminPage } from '../pages/AdminPage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { SupportPage } from '../pages/SupportPage'
import { DeveloperPage } from '../pages/DeveloperPage'
import { TraceWorkspaceProvider } from './TraceWorkspace'

export function App() {
  const [queryClient] = useState(createQueryClient)

  return (
    <QueryClientProvider client={queryClient}>
      <TraceWorkspaceProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<AppFrame />}>
              <Route index element={<Navigate replace to="/store" />} />
              <Route path="/store" element={<SupportPage />} />
              <Route path="/support" element={<Navigate replace to="/store" />} />
              <Route path="/admin" element={<AdminPage />} />
              <Route path="/developer" element={<DeveloperPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </TraceWorkspaceProvider>
    </QueryClientProvider>
  )
}
