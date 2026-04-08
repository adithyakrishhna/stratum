import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { GitPullRequest } from 'lucide-react'
import { Doughnut } from 'react-chartjs-2'
import { Chart as ChartJS, ArcElement, Tooltip, Legend } from 'chart.js'

import api from '../services/api'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import { RepoSelector, useRepos } from '../components/RepoSelector'

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

export default function PrReview() {
  const { data: reposData } = useRepos()
  const repos = reposData?.data || []
  const stored = localStorage.getItem('stratum_repo_id')
  const ids = repos.map((r) => r.id)
  const [repoId, setRepoId] = useState(ids.includes(stored) ? stored : (ids[0] || null))
  const handleRepoChange = (id) => { localStorage.setItem('stratum_repo_id', id); setRepoId(id) }

  const { data, isLoading } = useQuery({
    queryKey: ['prs', repoId],
    queryFn: () => api.get(`/dashboard/${repoId}/prs/`).then((r) => r.data),
    enabled: !!repoId,
    refetchInterval: 30_000,
  })

  const prs = data?.data || []
  const reviewed = prs.filter((p) => p.reviewed_at)
  const avgHealth = reviewed.length ? Math.round(reviewed.reduce((s, p) => s + (p.health_score || 0), 0) / reviewed.length) : null

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8 max-w-6xl mx-auto w-full">
      <PageHeader icon={GitPullRequest} title="PR Review Center" subtitle="All pull requests, findings breakdown, and debt impact per PR." right={<RepoSelector value={repoId} onChange={handleRepoChange} />} />

      {!repoId && <div className="text-center py-20 text-fg-muted text-sm">Select a repository.</div>}
      {repoId && isLoading && <div className="flex justify-center py-20"><div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>}

      {!isLoading && repoId && <>
        <div className="grid grid-cols-3 gap-3 mb-6">
          <StatCard label="Total PRs" value={prs.length} />
          <StatCard label="Reviewed" value={reviewed.length} />
          <StatCard label="Avg Health" value={avgHealth != null ? `${avgHealth}/100` : '—'} color={avgHealth >= 80 ? 'text-success' : avgHealth >= 50 ? 'text-warning' : 'text-danger'} />
        </div>

        {prs.length > 0 && (
          <div className="rounded-lg border border-border bg-canvas-subtle p-4 mb-6">
            <div className="text-sm font-medium text-fg mb-3">Findings by Severity (all PRs combined)</div>
            <FindingsDonut prs={prs} />
          </div>
        )}

        {prs.length === 0
          ? <div className="text-center py-12 text-fg-muted text-sm">No PRs reviewed yet.</div>
          : <div className="rounded-lg border border-border overflow-hidden">
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
                  {prs.map((pr) => {
                    const topSev = ['critical','high','medium','low','info'].find((s) => pr.findings_by_severity[s] > 0)
                    const debtPct = pr.debt_impact_score != null ? Math.round(pr.debt_impact_score * 100) : null
                    return (
                      <tr key={pr.id} className="border-b border-border-muted last:border-0 hover:bg-border-muted/20 transition-colors">
                        <td className="px-4 py-3">
                          <div className="font-medium text-fg truncate max-w-[200px]" title={pr.title}>#{pr.github_pr_number} {pr.title}</div>
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
