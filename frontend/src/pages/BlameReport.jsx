import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { GitCommit, Download, ExternalLink } from 'lucide-react'

import api from '../services/api'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import { RepoSelector, useRepos } from '../components/RepoSelector'

function DebtBar({ score, max }) {
  const pct = max > 0 ? Math.min(100, (score / max) * 100) : 0
  const color = pct > 66 ? 'bg-danger' : pct > 33 ? 'bg-warning' : 'bg-accent'
  return (
    <div className="flex items-center gap-2 min-w-[80px]">
      <div className="flex-1 h-1.5 bg-border-muted rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-fg-muted w-8 text-right">{score}</span>
    </div>
  )
}

export default function BlameReport() {
  const { data: reposData } = useRepos()
  const repos = reposData?.data || []
  const stored = localStorage.getItem('stratum_repo_id')
  const ids = repos.map((r) => r.id)
  const [repoId, setRepoId] = useState(ids.includes(stored) ? stored : (ids[0] || null))
  const handleRepoChange = (id) => { localStorage.setItem('stratum_repo_id', id); setRepoId(id) }

  const repoFullName = repos.find((r) => r.id === repoId)?.full_name || ''
  const ghCommitUrl = (sha) => repoFullName && sha ? `https://github.com/${repoFullName}/commit/${sha}` : null

  const { data, isLoading } = useQuery({
    queryKey: ['blame', repoId],
    queryFn: () => api.get(`/dashboard/${repoId}/blame/`).then((r) => r.data),
    enabled: !!repoId,
  })

  const entries = data?.data || []
  const maxScore = entries.length ? entries[0].debt_introduced_score : 0
  const totalPatterns = entries.reduce((s, e) => s + e.patterns_originated, 0)

  const handleExportCSV = () => {
    window.location.href = `/api/dashboard/${repoId}/blame/?format=csv`
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8 max-w-6xl mx-auto w-full">
      <PageHeader
        icon={GitCommit}
        title="Blame Report"
        subtitle="Commits ranked by debt introduced — by patterns originated and spread, not by lines changed."
        right={
          <div className="flex items-center gap-3">
            <RepoSelector value={repoId} onChange={handleRepoChange} />
            {entries.length > 0 && (
              <button
                onClick={handleExportCSV}
                className="flex items-center gap-1.5 px-3 h-8 rounded-md text-sm border border-border text-fg-muted hover:text-fg hover:border-fg-muted transition-colors"
              >
                <Download size={13} /> CSV
              </button>
            )}
          </div>
        }
      />

      {!repoId && <div className="text-center py-20 text-fg-muted text-sm">Select a repository.</div>}
      {repoId && isLoading && <div className="flex justify-center py-20"><div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>}

      {!isLoading && repoId && <>
        <div className="grid grid-cols-3 gap-3 mb-6">
          <StatCard label="Commits Analyzed" value={entries.length} />
          <StatCard label="Patterns Originated" value={totalPatterns} />
          <StatCard label="Top Debt Commit" value={maxScore > 0 ? maxScore : '—'} color="text-danger" sub="debt score" />
        </div>

        {entries.length === 0
          ? <div className="text-center py-12 text-fg-muted text-sm">No blame data yet — run an analysis first.</div>
          : <div className="rounded-lg border border-border overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-canvas-subtle border-b border-border">
                  <tr>
                    <th className="px-4 py-3 text-left text-fg-subtle font-medium">Commit</th>
                    <th className="px-4 py-3 text-left text-fg-subtle font-medium hidden md:table-cell">Author</th>
                    <th className="px-4 py-3 text-left text-fg-subtle font-medium hidden lg:table-cell">Date</th>
                    <th className="px-4 py-3 text-left text-fg-subtle font-medium">Debt Score</th>
                    <th className="px-4 py-3 text-left text-fg-subtle font-medium hidden sm:table-cell">Patterns</th>
                    <th className="px-4 py-3 text-left text-fg-subtle font-medium hidden sm:table-cell">Files Affected</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((e) => (
                    <tr key={e.full_sha} className="border-b border-border-muted last:border-0 hover:bg-border-muted/20 transition-colors">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono text-xs text-accent">{e.commit_sha}</span>
                          {ghCommitUrl(e.full_sha) && (
                            <a href={ghCommitUrl(e.full_sha)} target="_blank" rel="noopener noreferrer" className="text-fg-muted hover:text-accent shrink-0" title="Open on GitHub">
                              <ExternalLink size={11} />
                            </a>
                          )}
                        </div>
                        <div className="text-xs text-fg-muted mt-0.5 max-w-[180px] truncate" title={e.message}>{e.message}</div>
                      </td>
                      <td className="px-4 py-3 text-fg-muted hidden md:table-cell">
                        <div>{e.author_name}</div>
                        <div className="text-xs">{e.author_email}</div>
                      </td>
                      <td className="px-4 py-3 text-fg-muted text-xs hidden lg:table-cell">
                        {new Date(e.committed_at).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3">
                        <DebtBar score={e.debt_introduced_score} max={maxScore} />
                      </td>
                      <td className="px-4 py-3 hidden sm:table-cell">
                        {e.patterns_originated > 0
                          ? <span className="text-warning font-medium">{e.patterns_originated}</span>
                          : <span className="text-fg-subtle">0</span>}
                      </td>
                      <td className="px-4 py-3 hidden sm:table-cell text-fg-muted">{e.files_eventually_affected}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
        }
      </>}
    </div>
  )
}
