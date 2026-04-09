import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { TrendingUp, ExternalLink, Copy, Check } from 'lucide-react'
import { Line } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement,
  LineElement, Tooltip, Legend,
} from 'chart.js'

import api from '../services/api'
import PageHeader from '../components/PageHeader'
import { RepoSelector, useRepos } from '../components/RepoSelector'

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false)
  const handle = () => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button onClick={handle} className="text-fg-muted hover:text-accent transition-colors" title="Copy SHA">
      {copied ? <Check size={11} className="text-success" /> : <Copy size={11} />}
    </button>
  )
}

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend)

export default function DebtTimeline() {
  const { data: reposData } = useRepos()
  const repos = reposData?.data || []
  const stored = localStorage.getItem('stratum_repo_id')
  const ids = repos.map((r) => r.id)
  const [repoId, setRepoId] = useState(ids.includes(stored) ? stored : (ids[0] || null))
  const handleRepoChange = (id) => { localStorage.setItem('stratum_repo_id', id); setRepoId(id) }

  const repoFullName = repos.find((r) => r.id === repoId)?.full_name || ''
  const ghCommitUrl = (sha) => repoFullName && sha ? `https://github.com/${repoFullName}/commit/${sha}` : null

  const [filePath, setFilePath] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['debt-timeline', repoId, filePath],
    queryFn: () => api.get(`/dashboard/${repoId}/debt/timeline/`, { params: { file_path: filePath || undefined } }).then((r) => r.data),
    enabled: !!repoId,
  })

  const d = data?.data
  const timeline = d?.timeline || []
  const fileList = d?.file_list || []

  const inflectionPoints = timeline
    .map((t, i) => ({ i, t }))
    .filter(({ t }) => t.is_inflection)

  const chartData = {
    labels: timeline.map((t) => t.commit_sha),
    datasets: [
      {
        label: 'Debt Score',
        data: timeline.map((t) => t.total_score),
        borderColor: '#58a6ff',
        backgroundColor: 'rgba(88,166,255,0.06)',
        borderWidth: 2,
        pointRadius: timeline.map((_, i) =>
          inflectionPoints.some(({ i: idx }) => idx === i) ? 7 : 3
        ),
        pointBackgroundColor: timeline.map((t) =>
          t.is_inflection ? '#f85149' : '#58a6ff'
        ),
        fill: true,
        tension: 0.3,
      },
      {
        label: 'Velocity',
        data: timeline.map((t) => t.velocity),
        borderColor: '#d29922',
        backgroundColor: 'transparent',
        borderWidth: 1.5,
        borderDash: [4, 4],
        pointRadius: 2,
        tension: 0.3,
      },
    ],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { labels: { color: '#8b949e', font: { size: 12 } } },
      tooltip: {
        callbacks: {
          title: (items) => {
            const idx = items[0].dataIndex
            const t = timeline[idx]
            return [`Commit: ${t.commit_sha}`, t.message]
          },
          afterLabel: (item) => {
            const t = timeline[item.dataIndex]
            return t.is_inflection ? '⚠ Inflection point' : ''
          },
        },
      },
    },
    scales: {
      x: { ticks: { color: '#6e7681', maxTicksLimit: 10, font: { size: 11 } }, grid: { color: '#21262d' } },
      y: { ticks: { color: '#6e7681', font: { size: 11 } }, grid: { color: '#21262d' } },
    },
    onClick: (_e, elements) => {
      if (!elements.length) return
      const t = timeline[elements[0].index]
      const url = ghCommitUrl(t.full_sha || t.commit_sha)
      if (url) window.open(url, '_blank', 'noopener,noreferrer')
    },
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8 max-w-6xl mx-auto w-full">
      <PageHeader
        icon={TrendingUp}
        title="Debt Timeline"
        subtitle="File-level debt score over every commit. Red dots = inflection points (sharp debt jumps)."
        right={<RepoSelector value={repoId} onChange={handleRepoChange} />}
      />

      {!repoId && <div className="text-center py-20 text-fg-muted text-sm">Select a repository.</div>}
      {repoId && isLoading && <div className="flex justify-center py-20"><div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>}

      {!isLoading && repoId && <>
        {/* File selector */}
        <div className="mb-4">
          <select
            value={filePath || d?.file_path || ''}
            onChange={(e) => setFilePath(e.target.value)}
            className="h-8 px-3 text-sm rounded-md bg-canvas-subtle border border-border text-fg focus:outline-none focus:border-accent"
          >
            {fileList.map((f) => <option key={f} value={f}>{f}</option>)}
            {fileList.length === 0 && <option value="">No files tracked yet</option>}
          </select>
          {inflectionPoints.length > 0 && (
            <span className="ml-3 text-xs text-danger">
              {inflectionPoints.length} inflection point{inflectionPoints.length !== 1 ? 's' : ''} detected
            </span>
          )}
        </div>

        {timeline.length === 0
          ? <div className="text-center py-20 text-fg-muted text-sm">No debt data for this file yet.</div>
          : <>
              <div className="rounded-lg border border-border bg-canvas-subtle p-4 mb-6">
                <div className="h-64">
                  <Line data={chartData} options={options} />
                </div>
              </div>

              {/* Inflection point list */}
              {inflectionPoints.length > 0 && (
                <div className="rounded-lg border border-danger/30 bg-danger-subtle/20 p-4">
                  <div className="text-sm font-medium text-danger mb-2">Inflection Points</div>
                  <div className="space-y-2">
                    {inflectionPoints.map(({ t }) => (
                      <div key={t.commit_sha} className="flex items-start gap-3 text-sm">
                        <div className="flex items-center gap-1 shrink-0 mt-0.5">
                          <span className="font-mono text-xs text-fg-muted">{t.commit_sha}</span>
                          <CopyButton text={t.full_sha || t.commit_sha} />
                          {ghCommitUrl(t.full_sha || t.commit_sha) && (
                            <a href={ghCommitUrl(t.full_sha || t.commit_sha)} target="_blank" rel="noopener noreferrer" className="text-fg-muted hover:text-accent" title="Open on GitHub">
                              <ExternalLink size={11} />
                            </a>
                          )}
                        </div>
                        <span className="text-fg">{t.message}</span>
                        <span className="ml-auto text-danger shrink-0">+{t.velocity}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
        }
      </>}
    </div>
  )
}
