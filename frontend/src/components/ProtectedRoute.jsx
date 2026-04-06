import { useQuery } from '@tanstack/react-query'
import api from '../services/api'

function ProtectedRoute({ children }) {
  const { isLoading, isError } = useQuery({
    queryKey: ['currentUser'],
    queryFn: () => api.get('/repositories/me/').then((r) => r.data),
    retry: false,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-canvas">
        <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  // api.js interceptor handles the redirect to /accounts/login/ on 401
  if (isError) return null

  return children
}

export default ProtectedRoute
