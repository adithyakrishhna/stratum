import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { GitPullRequest, ExternalLink, Search, PauseCircle, PlayCircle } from 'lucide-react'
import { Doughnut } from 'react-chartjs-2'
import { Chart as ChartJS, ArcElement, Tooltip, Legend } from 'chart.js'

import api from '../services/api'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import { RepoSelector, useRepoId } from '../components/RepoSelector'

ChartJS.register(ArcElement, Tooltip, Legend)

const SEV_COLORS = { critical: '#f85149', high: '#d29922', medium: '#e3b341', low: '#58a6ff', info: '#6e7681' }
const SEV_BG     = { critical: 'bg-danger-subtle text-danger', high: 'bg-warning-subtle text-warning', medium: 'bg-yellow-900/30 text-yellow-400', low: 'bg-accent/10 text-accent', info: 'bg-border-muted text-fg-muted' }

function SeverityBadge({ sev }) {
  return <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${SEV_BG[sev] || 'bg-border-muted text-fg-muted'}`}>{sev}</span>
}

function StatusBadge({ status }) {
  const c = { open: 'bg-success-subtle text-success', analyzing: 'bg-accent/10 text-accent', closed: 'bg-border-muted text-fg-muted', merged: 'bg-accent/20 text-accent' }
  return <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${c[status] || 'bg-border-muted text-fg-muted'}`}>{status}</span>
}

function FindingsDonut({ prs }) {
  const totals = { critical: 0, high: 0, medium: 0, low: 0, info: 0 }
  prs.forEach((pr) => Object.entries(pr.findings_by_severity).forEach(([k, v]) => { totals[k] += v }))
  const labels = Object.keys(totals).filter((k) => totals[k] > 0)
  if (!labels.length) return <p className="text-sm text-fg-muted text-center py-6">No findings yet.</p>
  const data = { labels, datasets: [{ data: labels.map((l) => totals[l]), backgroundColor: labels.map((l) => SEV_COLORS[l]), borderWidth: 0 }] }
  const options = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { color: '#8b949e', boxWidth: 12, font: { size: 12 } } } }, cutout: '65%' }
  return <div className="h-44"><Doughnut data={data} options={options} /></div>
}

const STATUS_OPTIONS = ['all', 'open', 'analyzing', 'closed', 'merged']
const SEV_OPTIONS    = ['all', 'critical', 'high', 'medium', 'low', 'clean']

function FilterPills({ value, options, onChange }) {
  return (
    <div className="flex gap-1.5 flex-wrap">
      {options.map((o) => (
        <button
          key={o}
          onClick={() => onChange(o)}
          className={`px-2.5 py-1 rounded text-xs border transition-colors ${value === o ? 'border-accent text-accent bg-accent/10' : 'border-border text-fg-muted hover:text-fg'}`}
        >
          {o}
        </button>
      ))}
    </div>
  )
}

export default function PrReview() {
  const qc = useQueryClient()
  const { repos, repoId, setRepoId } = useRepoId()
  const handleRepoChange = (id) => setRepoId(id)

  const currentRepo = repos.find((r) => r.id === repoId)
  const repoFullName = currentRepo?.full_name || ''
  const prReviewEnabled = currentRepo?.pr_review_enabled ?? true
  const ghPrUrl = (num) => repoFullName ? `https://github.com/${repoFullName}/pull/${num}` : null

  const [search, setSearch]       = useState('')
  const [statusFilter, setStatus] = useState('all')
  const [sevFilter, setSev]       = useState('all')

  const toggleMutation = useMutation({
    mutationFn: () => api.post(`/repositories/${repoId}/toggle-pr-review/`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['repos'] })
    },
    onError: (err) => {
      console.error('toggle-pr-review failed:', err?.response?.data || err.message)
    },
  })

  const { data, isLoading } = useQuery({
    queryKey: ['prs', repoId],
    queryFn: () => api.get(`/dashboard/${repoId}/prs/`).then((r) => r.data),
    enabled: !!repoId,
    refetchInterval: 30_000,
  })

  const allPrs = data?.data || []
  const reviewed = allPrs.filter((p) => p.reviewed_at)
  const avgHealth = reviewed.length ? Math.round(reviewed.reduce((s, p) => s + (p.health_score || 0), 0) / reviewed.length) : null

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return allPrs.filter((pr) => {
      if (statusFilter !== 'all' && pr.status !== statusFilter) return false
      if (sevFilter === 'clean') {
        if (pr.total_findings > 0) return false
      } else if (sevFilter !== 'all') {
        if (!(pr.findings_by_severity[sevFilter] > 0)) return false
      }
      if (q && !pr.title?.toLowerCase().includes(q) && !pr.author?.toLowerCase().includes(q) && !pr.head_branch?.toLowerCase().includes(q)) return false
      return true
    })
  }, [allPrs, search, statusFilter, sevFilter])

  const hasActiveFilter = search || statusFilter !== 'all' || sevFilter !== 'all'

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8 max-w-6xl mx-auto w-full">
      <PageHeader
        icon={GitPullRequest}
        title="PR Review Center"
        subtitle="All pull requests, findings breakdown, and debt impact per PR."
        right={
          <div className="flex items-center gap-3">
            <RepoSelector value={repoId} onChange={handleRepoChange} />
            {repoId && (
              <button
                onClick={() => toggleMutation.mutate()}
                disabled={toggleMutation.isPending}
                title={prReviewEnabled ? 'Pause PR review — Stratum will stop commenting on new PRs' : 'Resume PR review'}
                className={`flex items-center gap-1.5 px-3 h-8 rounded-md text-xs border transition-colors disabled:opacity-50 ${
                  prReviewEnabled
                    ? 'border-border text-fg-muted hover:border-warning hover:text-warning'
                    : 'border-warning text-warning bg-warning/10 hover:bg-warning/20'
                }`}
              >
                {prReviewEnabled
                  ? <><PauseCircle size={13} /> Pause review</>
                  : <><PlayCircle size={13} /> Resume review</>
                }
              </button>
            )}
          </div>
        }
      />

      {!repoId && <div className="text-center py-20 text-fg-muted text-sm">Select a repository.</div>}
      {repoId && isLoading && <div className="flex justify-center py-20"><div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>}

      {repoId && !prReviewEnabled && (
        <div className="mb-4 flex items-center gap-3 px-4 py-3 rounded-lg border border-warning/40 bg-warning/5 text-warning text-sm">
          <PauseCircle size={16} className="shrink-0" />
          <span>PR review is <strong>paused</strong> for this repository. Stratum will not comment on new pull requests. Use the <strong>Resume review</strong> button above to re-enable.</span>
        </div>
      )}

      {!isLoading && repoId && <>
        <div className="grid grid-cols-3 gap-3 mb-6">
          <StatCard label="Total PRs" value={allPrs.length} />
          <StatCard label="Reviewed" value={reviewed.length} />
          <StatCard label="Avg Health" value={avgHealth != null ? `${avgHealth}/100` : '—'} color={avgHealth >= 80 ? 'text-success' : avgHealth >= 50 ? 'text-warning' : 'text-danger'} />
        </div>

        {allPrs.length > 0 && (
          <div className="rounded-lg border border-border bg-canvas-subtle p-4 mb-6">
            <div className="text-sm font-medium text-fg mb-3">Findings by Severity (all PRs combined)</div>
            <FindingsDonut prs={allPrs} />
          </div>
        )}

        {allPrs.length > 0 && (
          <div className="mb-4 space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="relative">
                <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted pointer-events-none" />
                <input
                  type="text"
                  placeholder="Search title, author, branch…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="h-8 pl-7 pr-3 text-xs rounded-md bg-canvas-subtle border border-border text-fg placeholder-fg-subtle focus:outline-none focus:border-accent w-56"
                />
              </div>
              {hasActiveFilter && (
                <button onClick={() => { setSearch(''); setStatus('all'); setSev('all') }} className="text-xs text-fg-muted hover:text-fg underline underline-offset-2">
                  Clear filters
                </button>
              )}
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-xs text-fg-muted w-12">Status:</span>
              <FilterPills value={statusFilter} options={STATUS_OPTIONS} onChange={setStatus} />
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-xs text-fg-muted w-12">Severity:</span>
              <FilterPills value={sevFilter} options={SEV_OPTIONS} onChange={setSev} />
            </div>
          </div>
        )}

        {allPrs.length === 0
          ? <div className="text-center py-12 text-fg-muted text-sm">No PRs reviewed yet.</div>
          : filtered.length === 0
            ? <div className="text-center py-12 text-fg-muted text-sm">No PRs match the current filters.</div>
            : <div className="rounded-lg border border-border overflow-hidden">
                <div className="px-4 py-2 bg-canvas-subtle border-b border-border text-xs text-fg-muted">
                  Showing {filtered.length} of {allPrs.length} pull request{allPrs.length !== 1 ? 's' : ''}
                </div>
                <table className="w-full text-sm">
                  <thead className="bg-canvas-subtle border-b border-border">
                    <tr>
                      <th className="px-4 py-3 text-left text-fg-subtle font-medium">Pull Request</th>
                      <th className="px-4 py-3 text-left text-fg-subtle font-medium hidden md:table-cell">Author</th>
                      <th className="px-4 py-3 text-left text-fg-subtle font-medium">Status</th>
                      <th className="px-4 py-3 text-left text-fg-subtle font-medium hidden sm:table-cell">Health</th>
                      <th className="px-4 py-3 text-left text-fg-subtle font-medium hidden lg:table-cell">Debt Impact</th>
                      <th className="px-4 py-3 text-left text-fg-subtle font-medium">Top Finding</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((pr) => {
                      const topSev = ['critical','high','medium','low','info'].find((s) => pr.findings_by_severity[s] > 0)
                      const debtPct = pr.debt_impact_score != null ? Math.round(pr.debt_impact_score * 100) : null
                      return (
                        <tr key={pr.id} className="border-b border-border-muted last:border-0 hover:bg-border-muted/20 transition-colors">
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-1.5">
                              <span className="font-medium text-fg truncate max-w-[180px]" title={pr.title}>#{pr.github_pr_number} {pr.title}</span>
                              {ghPrUrl(pr.github_pr_number) && (
                                <a href={ghPrUrl(pr.github_pr_number)} target="_blank" rel="noopener noreferrer" className="text-fg-muted hover:text-accent shrink-0" title="Open on GitHub">
                                  <ExternalLink size={12} />
                                </a>
                              )}
                            </div>
                            <div className="text-xs text-fg-muted mt-0.5 font-mono">{pr.head_branch}</div>
                          </td>
                          <td className="px-4 py-3 text-fg-muted hidden md:table-cell">{pr.author}</td>
                          <td className="px-4 py-3"><StatusBadge status={pr.status} /></td>
                          <td className="px-4 py-3 hidden sm:table-cell">
                            {pr.health_score != null
                              ? <span className={pr.health_score >= 80 ? 'text-success' : pr.health_score >= 50 ? 'text-warning' : 'text-danger'}>{Math.round(pr.health_score)}/100</span>
                              : <span className="text-fg-subtle">—</span>}
                          </td>
                          <td className="px-4 py-3 hidden lg:table-cell">
                            {debtPct != null
                              ? <span className={debtPct >= 30 ? 'text-danger font-medium' : debtPct >= 10 ? 'text-warning' : 'text-fg-muted'}>{debtPct}%</span>
                              : <span className="text-fg-subtle">—</span>}
                          </td>
                          <td className="px-4 py-3">
                            {topSev
                              ? <div className="flex items-center gap-1.5">
                                  <SeverityBadge sev={topSev} />
                                  {pr.total_findings > 1 && <span className="text-xs text-fg-muted">+{pr.total_findings - 1}</span>}
                                </div>
                              : <span className="text-success text-xs">Clean</span>}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
        }
      </>}
    </div>
  )
}
