import { useQuery } from '@tanstack/react-query'
import api from '../services/api'

/**
 * Dropdown that lets the user pick a repository.
 * Stores the selected repo_id in localStorage so it persists across pages.
 */
export function useRepos() {
  return useQuery({
    queryKey: ['repos'],
    queryFn: () => api.get('/repositories/').then((r) => r.data),
  })
}

export function RepoSelector({ value, onChange }) {
  const { data, isLoading } = useRepos()
  const repos = data?.data || []

  if (isLoading) {
    return (
      <div className="h-8 w-48 rounded-md bg-border-muted animate-pulse" />
    )
  }

  if (!repos.length) {
    return (
      <span className="text-sm text-fg-muted italic">No repositories connected</span>
    )
  }

  return (
    <select
      value={value || ''}
      onChange={(e) => onChange(e.target.value)}
      className="h-8 px-3 text-sm rounded-md bg-canvas-subtle border border-border
                 text-fg focus:outline-none focus:border-accent cursor-pointer"
    >
      {!value && <option value="" disabled>Select repository…</option>}
      {repos.map((r) => (
        <option key={r.id} value={r.id}>{r.full_name}</option>
      ))}
    </select>
  )
}

/** Hook: returns [repoId, setRepoId] — persists to localStorage. */
export function useSelectedRepo(repos) {
  const stored = localStorage.getItem('stratum_repo_id')
  const ids = (repos || []).map((r) => r.id)
  const valid = ids.includes(stored) ? stored : (ids[0] || null)
  return [
    valid,
    (id) => {
      localStorage.setItem('stratum_repo_id', id)
      // Force re-render by navigating (pages call window.location or use state)
    },
  ]
}
