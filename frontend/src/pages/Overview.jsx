import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { LayoutDashboard, RefreshCw } from 'lucide-react'
import { Line } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement,
  LineElement, Tooltip, Filler,
} from 'chart.js'

import api from '../services/api'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import { RepoSelector, useRepos } from '../components/RepoSelector'
import { useWebSocket } from '../hooks/useWebSocket'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler)

function DebtTrendChart({ trend }) {
  if (!trend?.length) {
    return (
      <div className="flex items-center justify-center h-48 text-fg-subtle text-sm">
        No debt history yet — run an analysis first.
      </div>
    )
  }
  const data = {
    labels: trend.map((t) => t.commit_sha),
    datasets: [{
      label: 'Avg Debt Score',
      data: trend.map((t) => t.avg_debt_score),
      borderColor: '#58a6ff',
      backgroundColor: 'rgba(88,166,255,0.08)',
      borderWidth: 2,
      pointRadius: 3,
      fill: true,
      tension: 0.3,
    }],
  }
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { mode: 'index' } },
    scales: {
      x: { ticks: { color: '#6e7681', maxTicksLimit: 8, font: { size: 11 } }, grid: { color: '#21262d' } },
      y: { ticks: { color: '#6e7681', font: { size: 11 } }, grid: { color: '#21262d' } },
    },
  }
  return <div className="h-48"><Line data={data} options={options} /></div>
}

export default function Overview() {
  const { data: reposData } = useRepos()
  const repos = reposData?.data || []
  const stored = localStorage.getItem('stratum_repo_id')
  const ids = repos.map((r) => r.id)
  const [repoId, setRepoId] = useState(ids.includes(stored) ? stored : (ids[0] || null))

  const handleRepoChange = (id) => { localStorage.setItem('stratum_repo_id', id); setRepoId(id) }

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['overview', repoId],
    queryFn: () => api.get(`/dashboard/${repoId}/overview/`).then((r) => r.data),
    enabled: !!repoId,
    refetchInterval: 30_000,
  })

  const [wsEvents, setWsEvents] = useState([])
  useWebSocket(repoId, (msg) => setWsEvents((prev) => [msg, ...prev].slice(0, 5)))

  const d = data?.data
  const healthColor = !d?.health_score ? 'text-fg-muted'
    : d.health_score >= 80 ? 'text-success' : d.health_score >= 50 ? 'text-warning' : 'text-danger'

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8 max-w-6xl mx-auto w-full">
      <PageHeader
        icon={LayoutDashboard}
        title="Repository Overview"
        subtitle="Health score, debt trend, top deteriorating files, and live analysis progress."
        right={
          <div className="flex items-center gap-3">
            <RepoSelector value={repoId} onChange={handleRepoChange} />
            <button onClick={() => refetch()} className="p-1.5 rounded-md text-fg-muted hover:text-fg hover:bg-border-muted transition-colors" title="Refresh">
              <RefreshCw size={15} />
            </button>
          </div>
        }
      />

      {!repoId && <div className="text-center py-20 text-fg-muted text-sm">Select a repository to view overview.</div>}
      {repoId && isLoading && <div className="flex justify-center py-20"><div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>}

      {d && <>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <StatCard label="Health Score" value={d.health_score != null ? `${d.health_score}/100` : 'No PRs'} color={healthColor} sub="avg of last 5 PRs" />
          <StatCard label="Commits Analyzed" value={d.total_commits} />
          <StatCard label="Files Tracked" value={d.total_files} />
          <StatCard label="Spreading Patterns" value={d.spreading_pattern_count} color={d.spreading_pattern_count > 0 ? 'text-warning' : 'text-success'} sub="clusters growing > 10%" />
        </div>

        <div className="rounded-lg border border-border bg-canvas-subtle p-4 mb-6">
          <div className="text-sm font-medium text-fg mb-3">Debt Trend — last 30 commits</div>
          <DebtTrendChart trend={d.debt_trend} />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded-lg border border-border bg-canvas-subtle p-4">
            <div className="text-sm font-medium text-fg mb-3">Top Deteriorating Files</div>
            {d.top_deteriorating_files.length === 0
              ? <p className="text-sm text-fg-muted">No deteriorating files detected.</p>
              : <table className="w-full text-sm">
                  <thead><tr className="text-left text-fg-subtle border-b border-border">
                    <th className="pb-2 font-medium">File</th>
                    <th className="pb-2 font-medium text-right">Score</th>
                    <th className="pb-2 font-medium text-right">Velocity</th>
                  </tr></thead>
                  <tbody>
                    {d.top_deteriorating_files.map((f) => (
                      <tr key={f.file_path} className="border-b border-border-muted last:border-0">
                        <td className="py-2 font-mono text-xs text-fg truncate max-w-[160px]" title={f.file_path}>{f.file_path.split('/').pop()}</td>
                        <td className="py-2 text-right text-fg-muted">{f.total_score}</td>
                        <td className="py-2 text-right text-danger font-medium">+{f.velocity}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
            }
          </div>

          <div className="rounded-lg border border-border bg-canvas-subtle p-4">
            <div className="text-sm font-medium text-fg mb-3 flex items-center gap-2">
              Live Pipeline <span className="w-2 h-2 rounded-full bg-success animate-pulse" />
            </div>
            <div className="text-xs text-fg-subtle mb-2">Status: <span className="text-fg">{d.analysis_status}</span></div>
            {wsEvents.length === 0
              ? <p className="text-sm text-fg-muted">Waiting for pipeline events…</p>
              : <div className="space-y-2">
                  {wsEvents.map((e, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${e.status === 'completed' ? 'bg-success' : e.status === 'failed' ? 'bg-danger' : 'bg-warning'}`} />
                      <span className="text-fg">{e.stage}</span>
                      <span className="text-fg-muted ml-auto">{e.status}</span>
                    </div>
                  ))}
                </div>
            }
          </div>
        </div>
      </>}
    </div>
  )
}
