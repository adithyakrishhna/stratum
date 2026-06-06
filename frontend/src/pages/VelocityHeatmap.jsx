import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Flame, Search, ArrowUpDown } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import api from '../services/api'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import { RepoSelector, useRepoId } from '../components/RepoSelector'

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

const STATUS_OPTIONS = ['all', 'deteriorating', 'improving', 'stable']
const SORT_OPTIONS = [
  { value: 'velocity_desc', label: 'Velocity ↓' },
  { value: 'velocity_asc',  label: 'Velocity ↑' },
  { value: 'score_desc',    label: 'Debt Score ↓' },
  { value: 'score_asc',     label: 'Debt Score ↑' },
]

export default function VelocityHeatmap() {
  const { repoId, setRepoId } = useRepoId()
  const handleRepoChange = (id) => setRepoId(id)

  const [langFilter, setLangFilter]     = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [search, setSearch]             = useState('')
  const [sort, setSort]                 = useState('velocity_desc')
  const navigate = useNavigate()

  const { data, isLoading } = useQuery({
    queryKey: ['heatmap', repoId, langFilter],
    queryFn: () => api.get(`/dashboard/${repoId}/heatmap/`, { params: { language: langFilter || undefined } }).then((r) => r.data),
    enabled: !!repoId,
  })

  const allFiles = data?.data || []
  const languages = data?.meta?.languages || []
  const deteriorating = allFiles.filter((f) => f.status === 'deteriorating').length
  const improving = allFiles.filter((f) => f.status === 'improving').length

  const files = useMemo(() => {
    const q = search.toLowerCase()
    let result = allFiles.filter((f) => {
      if (statusFilter !== 'all' && f.status !== statusFilter) return false
      if (q && !f.file_path.toLowerCase().includes(q)) return false
      return true
    })
    const [field, dir] = sort.split('_')
    result = [...result].sort((a, b) => {
      const va = field === 'velocity' ? a.velocity : a.total_score
      const vb = field === 'velocity' ? b.velocity : b.total_score
      return dir === 'desc' ? vb - va : va - vb
    })
    return result
  }, [allFiles, statusFilter, search, sort])

  const hasActiveFilter = search || statusFilter !== 'all' || sort !== 'velocity_desc'

  const handleFileClick = (filePath) => {
    navigate('/dashboard/debt', { state: { filePath } })
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
          <StatCard label="Total Files" value={allFiles.length} />
          <StatCard label="Deteriorating" value={deteriorating} color={deteriorating > 0 ? 'text-danger' : 'text-fg'} sub="velocity > 5" />
          <StatCard label="Improving" value={improving} color={improving > 0 ? 'text-success' : 'text-fg'} sub="velocity < -1" />
        </div>

        {/* Language filter */}
        {languages.length > 1 && (
          <div className="mb-3 flex gap-2 flex-wrap">
            <button onClick={() => setLangFilter('')} className={`px-3 py-1 rounded text-xs border ${!langFilter ? 'border-accent text-accent bg-accent/10' : 'border-border text-fg-muted hover:text-fg'}`}>All</button>
            {languages.map((l) => (
              <button key={l} onClick={() => setLangFilter(l)} className={`px-3 py-1 rounded text-xs border ${langFilter === l ? 'border-accent text-accent bg-accent/10' : 'border-border text-fg-muted hover:text-fg'}`}>{l}</button>
            ))}
          </div>
        )}

        {/* Search + status + sort */}
        {allFiles.length > 0 && (
          <div className="mb-4 space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="relative">
                <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted pointer-events-none" />
                <input
                  type="text"
                  placeholder="Search file path…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="h-8 pl-7 pr-3 text-xs rounded-md bg-canvas-subtle border border-border text-fg placeholder-fg-subtle focus:outline-none focus:border-accent w-52"
                />
              </div>
              <div className="flex items-center gap-1.5">
                <ArrowUpDown size={13} className="text-fg-muted" />
                <select
                  value={sort}
                  onChange={(e) => setSort(e.target.value)}
                  className="h-8 px-2 text-xs rounded-md bg-canvas-subtle border border-border text-fg focus:outline-none focus:border-accent"
                >
                  {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
              {hasActiveFilter && (
                <button onClick={() => { setSearch(''); setStatusFilter('all'); setSort('velocity_desc') }} className="text-xs text-fg-muted hover:text-fg underline underline-offset-2">
                  Clear
                </button>
              )}
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              {STATUS_OPTIONS.map((o) => (
                <button
                  key={o}
                  onClick={() => setStatusFilter(o)}
                  className={`px-2.5 py-1 rounded text-xs border transition-colors ${statusFilter === o ? 'border-accent text-accent bg-accent/10' : 'border-border text-fg-muted hover:text-fg'}`}
                >
                  {o}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center gap-4 mb-4 text-xs text-fg-muted">
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-danger/30 inline-block border border-danger/40" />Deteriorating (velocity &gt; 5)</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-success/30 inline-block border border-success/40" />Improving (velocity &lt; -1)</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-border-muted/40 inline-block border border-border" />Stable</span>
        </div>

        {allFiles.length === 0
          ? <div className="text-center py-20 text-fg-muted text-sm">No debt scores computed yet — run an analysis first.</div>
          : files.length === 0
            ? <div className="text-center py-12 text-fg-muted text-sm">No files match the current filters.</div>
            : <div className="rounded-lg border border-border overflow-hidden">
                <div className="px-4 py-2 bg-canvas-subtle border-b border-border text-xs text-fg-muted">
                  Showing {files.length} of {allFiles.length} file{allFiles.length !== 1 ? 's' : ''}
                </div>
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
