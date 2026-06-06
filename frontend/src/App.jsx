import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import ProtectedRoute from './components/ProtectedRoute'
import Layout from './components/Layout'
import Login from './pages/Login'

import Overview          from './pages/Overview'
import PrReview          from './pages/PrReview'
import DebtTimeline      from './pages/DebtTimeline'
import ClusterMap        from './pages/ClusterMap'
import VelocityHeatmap   from './pages/VelocityHeatmap'
import BlameReport       from './pages/BlameReport'
import PipelineMonitor   from './pages/PipelineMonitor'
import ConnectRepository from './pages/ConnectRepository'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,       // data fresh for 30 s before background refetch
      retry: 1,
    },
  },
})

function DashboardRoutes() {
  return (
    <ProtectedRoute>
      <Layout>
        <Routes>
          <Route index                   element={<Overview />} />
          <Route path="pr"               element={<PrReview />} />
          <Route path="debt"             element={<DebtTimeline />} />
          <Route path="clusters"         element={<ClusterMap />} />
          <Route path="heatmap"          element={<VelocityHeatmap />} />
          <Route path="blame"            element={<BlameReport />} />
          <Route path="pipeline"         element={<PipelineMonitor />} />
          <Route path="connect"          element={<ConnectRepository />} />
        </Routes>
      </Layout>
    </ProtectedRoute>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/"           element={<Navigate to="/dashboard" replace />} />
          <Route path="/login"      element={<Login />} />
          <Route path="/dashboard/*" element={<DashboardRoutes />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
