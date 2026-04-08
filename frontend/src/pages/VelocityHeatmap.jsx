import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Flame } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import api from '../services/api'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import { RepoSelector, useRepos } from '../components/RepoSelector'

function velocityColor(velocity, status) {
  if (status === 'deteriorating') return 'bg-danger/20 border-danger/40 text-danger'
  if (status === 'improving')     return 'bg-success/20 border-success/40 text-success'
  return 'bg-border-muted/40 border-border text-fg-muted'
}

function VelocityBar({ velocity }) {
  const max = 20
  const pct = Math.min(100, Math.abs(velocity) / max * 100)
  const color = velocity > 5 ? 'bg-danger' : velocity < -1 ? 'bg-success' : 'bg-border'
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-border-muted rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-xs font-mono ${velocity > 0 ? 'text-danger' : velocity < 0 ? 'text-success' : 'text-fg-muted'}`}>
        {velocity > 0 ? '+' : ''}{velocity}
      </span>
    </div>
  )
}

export default function VelocityHeatmap() {
  const { data: reposData } = useRepos()
  const repos = reposData?.data || []
  const stored = localStorage.getItem('stratum_repo_id')
  const ids = repos.map((r) => r.id)
  const [repoId, setRepoId] = useState(ids.includes(stored) ? stored : (ids[0] || null))
  const handleRepoChange = (id) => { localStorage.setItem('stratum_repo_id', id); setRepoId(id) }

  const [langFilter, setLangFilter] = useState('')
  const navigate = useNavigate()

  const { data, isLoading } = useQuery({
    queryKey: ['heatmap', repoId, langFilter],
    queryFn: () => api.get(`/dashboard/${repoId}/heatmap/`, { params: { language: langFilter || undefined } }).then((r) => r.data),
    enabled: !!repoId,
  })

  const files = data?.data || []
  const languages = data?.meta?.languages || []
  const deteriorating = files.filter((f) => f.status === 'deteriorating').length
  const improving = files.filter((f) => f.status === 'improving').length

  const handleFileClick = (filePath) => {
    localStorage.setItem('stratum_debt_file', filePath)
    navigate('/dashboard/debt')
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8 max-w-6xl mx-auto w-full">
      <PageHeader
        icon={Flame}
        title="Velocity Heatmap"
        subtitle="Files colored by debt velocity. Click any file to open its Debt Timeline."
        right={<RepoSelector value={repoId} onChange={handleRepoChange} />}
      />

      {!repoId && <div className="text-center py-20 text-fg-muted text-sm">Select a repository.</div>}
      {repoId && isLoading && <div className="flex justify-center py-20"><div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>}

      {!isLoading && repoId && <>
        <div className="grid grid-cols-3 gap-3 mb-4">
          <StatCard label="Total Files" value={files.length} />
          <StatCard label="Deteriorating" value={deteriorating} color={deteriorating > 0 ? 'text-danger' : 'text-fg'} sub="velocity > 5" />
          <StatCard label="Improving" value={improving} color={improving > 0 ? 'text-success' : 'text-fg'} sub="velocity < -1" />
        </div>

        {languages.length > 1 && (
          <div className="mb-4 flex gap-2 flex-wrap">
            <button onClick={() => setLangFilter('')} className={`px-3 py-1 rounded text-xs border ${!langFilter ? 'border-accent text-accent bg-accent/10' : 'border-border text-fg-muted hover:text-fg'}`}>All</button>
            {languages.map((l) => (
              <button key={l} onClick={() => setLangFilter(l)} className={`px-3 py-1 rounded text-xs border ${langFilter === l ? 'border-accent text-accent bg-accent/10' : 'border-border text-fg-muted hover:text-fg'}`}>{l}</button>
            ))}
          </div>
        )}

        <div className="flex items-center gap-4 mb-4 text-xs text-fg-muted">
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-danger/30 inline-block border border-danger/40" />Deteriorating (velocity &gt; 5)</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-success/30 inline-block border border-success/40" />Improving (velocity &lt; -1)</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-border-muted/40 inline-block border border-border" />Stable</span>
        </div>

        {files.length === 0
          ? <div className="text-center py-20 text-fg-muted text-sm">No debt scores computed yet — run an analysis first.</div>
          : <div className="rounded-lg border border-border overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-canvas-subtle border-b border-border">
                  <tr>
                    <th className="px-4 py-3 text-left text-fg-subtle font-medium">File</th>
                    <th className="px-4 py-3 text-left text-fg-subtle font-medium hidden sm:table-cell">Language</th>
                    <th className="px-4 py-3 text-left text-fg-subtle font-medium">Velocity</th>
                    <th className="px-4 py-3 text-left text-fg-subtle font-medium hidden md:table-cell">Debt Score</th>
                  </tr>
                </thead>
                <tbody>
                  {files.map((f) => (
                    <tr
                      key={f.file_path}
                      onClick={() => handleFileClick(f.file_path)}
                      className="border-b border-border-muted last:border-0 hover:bg-border-muted/20 cursor-pointer transition-colors"
                    >
                      <td className="px-4 py-2.5">
                        <div className={`inline-flex items-center gap-2 px-2 py-0.5 rounded border text-xs font-mono ${velocityColor(f.velocity, f.status)}`}>
                          {f.file_path}
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-fg-muted hidden sm:table-cell text-xs">{f.language}</td>
                      <td className="px-4 py-2.5"><VelocityBar velocity={f.velocity} /></td>
                      <td className="px-4 py-2.5 text-fg-muted hidden md:table-cell">{f.total_score}</td>
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
