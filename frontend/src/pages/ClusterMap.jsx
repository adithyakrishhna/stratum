import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Layers, ExternalLink } from 'lucide-react'
import { Bubble } from 'react-chartjs-2'
import { Chart as ChartJS, LinearScale, PointElement, Tooltip, Legend } from 'chart.js'

import api from '../services/api'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import { RepoSelector, useRepos } from '../components/RepoSelector'

ChartJS.register(LinearScale, PointElement, Tooltip, Legend)

function growthColor(rate) {
  if (rate >= 0.30) return 'rgba(248,81,73,0.8)'   // red — fast growing
  if (rate >= 0.10) return 'rgba(210,153,34,0.8)'   // amber
  return 'rgba(88,166,255,0.6)'                      // blue — stable
}

export default function ClusterMap() {
  const { data: reposData } = useRepos()
  const repos = reposData?.data || []
  const stored = localStorage.getItem('stratum_repo_id')
  const ids = repos.map((r) => r.id)
  const [repoId, setRepoId] = useState(ids.includes(stored) ? stored : (ids[0] || null))
  const handleRepoChange = (id) => { localStorage.setItem('stratum_repo_id', id); setRepoId(id) }

  const repoFullName = repos.find((r) => r.id === repoId)?.full_name || ''
  const ghCommitUrl = (sha) => repoFullName && sha ? `https://github.com/${repoFullName}/commit/${sha}` : null

  const [langFilter, setLangFilter] = useState('')
  const [selected, setSelected] = useState(null)

  const { data, isLoading } = useQuery({
    queryKey: ['clusters', repoId],
    queryFn: () => api.get(`/dashboard/${repoId}/clusters/`).then((r) => r.data),
    enabled: !!repoId,
  })

  const clusters = (data?.data || []).filter((c) => !langFilter || c.language === langFilter)
  const languages = [...new Set((data?.data || []).map((c) => c.language))].sort()
  const flagged = clusters.filter((c) => c.is_flagged).length

  // Bubble chart: x=file_count, y=chunk_count, r=growth_rate*40+6
  const chartData = {
    datasets: [{
      label: 'Clusters',
      data: clusters.map((c, i) => ({
        x: c.file_count,
        y: c.chunk_count,
        r: Math.max(6, (c.growth_rate || 0) * 40 + 6),
        index: i,
      })),
      backgroundColor: clusters.map((c) => growthColor(c.growth_rate || 0)),
      borderColor: clusters.map((c) => c.is_flagged ? '#f85149' : 'transparent'),
      borderWidth: clusters.map((c) => c.is_flagged ? 2 : 0),
    }],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: (item) => {
            const c = clusters[item.dataIndex]
            return [
              `Pattern: ${c.label}`,
              `Language: ${c.language}`,
              `Files: ${c.file_count} | Functions: ${c.chunk_count}`,
              `Growth rate: ${Math.round((c.growth_rate || 0) * 100)}%`,
              c.is_flagged ? '⚠ Flagged as spreading anti-pattern' : '',
            ].filter(Boolean)
          },
        },
      },
    },
    scales: {
      x: { title: { display: true, text: 'Files Affected', color: '#6e7681' }, ticks: { color: '#6e7681' }, grid: { color: '#21262d' } },
      y: { title: { display: true, text: 'Functions in Cluster', color: '#6e7681' }, ticks: { color: '#6e7681' }, grid: { color: '#21262d' } },
    },
    onClick: (_, elements) => {
      if (elements.length) setSelected(clusters[elements[0].index])
    },
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8 max-w-6xl mx-auto w-full">
      <PageHeader
        icon={Layers}
        title="Semantic Cluster Map"
        subtitle="Bubble size = growth rate. Red = fast growing anti-pattern. Click a bubble for details."
        right={<RepoSelector value={repoId} onChange={handleRepoChange} />}
      />

      {!repoId && <div className="text-center py-20 text-fg-muted text-sm">Select a repository.</div>}
      {repoId && isLoading && <div className="flex justify-center py-20"><div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>}

      {!isLoading && repoId && <>
        <div className="grid grid-cols-3 gap-3 mb-4">
          <StatCard label="Total Clusters" value={clusters.length} />
          <StatCard label="Flagged Anti-Patterns" value={flagged} color={flagged > 0 ? 'text-danger' : 'text-success'} />
          <StatCard label="Languages" value={languages.length} />
        </div>

        {languages.length > 1 && (
          <div className="mb-4 flex gap-2 flex-wrap">
            <button onClick={() => setLangFilter('')} className={`px-3 py-1 rounded text-xs border ${!langFilter ? 'border-accent text-accent bg-accent/10' : 'border-border text-fg-muted hover:text-fg'}`}>All</button>
            {languages.map((l) => (
              <button key={l} onClick={() => setLangFilter(l)} className={`px-3 py-1 rounded text-xs border ${langFilter === l ? 'border-accent text-accent bg-accent/10' : 'border-border text-fg-muted hover:text-fg'}`}>{l}</button>
            ))}
          </div>
        )}

        {clusters.length === 0
          ? <div className="text-center py-20 text-fg-muted text-sm">No clusters yet — run a full analysis first.</div>
          : <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="lg:col-span-2 rounded-lg border border-border bg-canvas-subtle p-4">
                <div className="h-80">
                  <Bubble data={chartData} options={options} />
                </div>
                <div className="flex items-center gap-4 mt-3 text-xs text-fg-muted">
                  <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-accent/60 inline-block" />Stable</span>
                  <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-warning inline-block" />Growing (&gt;10%)</span>
                  <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-danger inline-block" />Fast growing (&gt;30%)</span>
                </div>
              </div>

              <div className="rounded-lg border border-border bg-canvas-subtle p-4">
                <div className="text-sm font-medium text-fg mb-3">
                  {selected ? 'Cluster Detail' : 'Click a bubble to inspect'}
                </div>
                {selected
                  ? <div className="space-y-3 text-sm">
                      <div><span className="text-fg-muted">Pattern:</span> <span className="text-fg font-medium">{selected.label}</span></div>
                      <div><span className="text-fg-muted">Language:</span> <span className="text-fg">{selected.language}</span></div>
                      <div><span className="text-fg-muted">Files affected:</span> <span className="text-fg">{selected.file_count}</span></div>
                      <div><span className="text-fg-muted">Functions:</span> <span className="text-fg">{selected.chunk_count}</span></div>
                      <div><span className="text-fg-muted">Growth rate:</span> <span className={selected.growth_rate >= 0.3 ? 'text-danger font-medium' : selected.growth_rate >= 0.1 ? 'text-warning' : 'text-success'}>{Math.round((selected.growth_rate || 0) * 100)}%</span></div>
                      {selected.origin_commit_sha && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-fg-muted">Origin commit:</span>
                          <span className="font-mono text-xs text-fg">{selected.origin_commit_sha}</span>
                          {ghCommitUrl(selected.origin_commit_full_sha || selected.origin_commit_sha) && (
                            <a href={ghCommitUrl(selected.origin_commit_full_sha || selected.origin_commit_sha)} target="_blank" rel="noopener noreferrer" className="text-fg-muted hover:text-accent" title="Open on GitHub">
                              <ExternalLink size={11} />
                            </a>
                          )}
                        </div>
                      )}
                      {selected.first_seen_at && <div><span className="text-fg-muted">First seen:</span> <span className="text-fg">{new Date(selected.first_seen_at).toLocaleDateString()}</span></div>}
                      {selected.is_flagged && <div className="mt-2 px-3 py-2 rounded bg-danger-subtle text-danger text-xs">⚠ Flagged as spreading anti-pattern</div>}
                    </div>
                  : <p className="text-fg-subtle text-sm">Select a cluster bubble to see its details, origin commit, and growth history.</p>
                }
              </div>
            </div>
        }
      </>}
    </div>
  )
}
