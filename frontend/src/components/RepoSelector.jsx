import { useState, useEffect } from 'react'
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

/**
 * Hook: returns { repos, repoId, setRepoId }.
 * Syncs repoId with the loaded repo list — handles stale localStorage
 * (e.g. after a repo is deleted/reconnected) without requiring a manual
 * browser cache clear.
 */
export function useRepoId() {
  const { data: reposData } = useRepos()
  const repos = reposData?.data || []

  const [repoId, setRepoIdRaw] = useState(() => {
    const stored = localStorage.getItem('stratum_repo_id')
    const ids = repos.map((r) => r.id)
    return ids.includes(stored) ? stored : (ids[0] || null)
  })

  // Runs whenever the repo list loads or changes.
  // If the stored/current repoId is no longer valid, picks the first available repo.
  const repoKey = repos.map((r) => r.id).join(',')
  useEffect(() => {
    if (!repos.length) return
    const stored = localStorage.getItem('stratum_repo_id')
    if (stored && repos.some((r) => r.id === stored)) {
      if (repoId !== stored) setRepoIdRaw(stored)
    } else if (!repoId || !repos.some((r) => r.id === repoId)) {
      const first = repos[0].id
      localStorage.setItem('stratum_repo_id', first)
      setRepoIdRaw(first)
    }
  }, [repoKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const setRepoId = (id) => {
    localStorage.setItem('stratum_repo_id', id)
    setRepoIdRaw(id)
  }

  return { repos, repoId, setRepoId }
}
