import { useState, useMemo, useRef, useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { TrendingUp, ExternalLink, Copy, Check, Search, X } from 'lucide-react'
import { Line } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement,
  LineElement, Tooltip, Legend,
} from 'chart.js'

import api from '../services/api'
import PageHeader from '../components/PageHeader'
import { RepoSelector, useRepoId } from '../components/RepoSelector'

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

function FileSearch({ fileList, value, onChange }) {
  const [query, setQuery] = useState(value || '')
  const [open, setOpen] = useState(false)
  const containerRef = useRef(null)

  // Keep input in sync when value changes externally (e.g. from heatmap nav)
  useEffect(() => { if (value) setQuery(value) }, [value])

  // Close dropdown when clicking outside
  useEffect(() => {
    const handler = (e) => { if (!containerRef.current?.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const filtered = useMemo(() => {
    if (!query) return fileList.slice(0, 50)
    const q = query.toLowerCase()
    return fileList.filter((f) => f.toLowerCase().includes(q)).slice(0, 50)
  }, [fileList, query])

  const select = (f) => {
    onChange(f)
    setQuery(f)
    setOpen(false)
  }

  const clear = () => {
    onChange('')
    setQuery('')
  }

  return (
    <div ref={containerRef} className="relative w-full max-w-md">
      <div className="relative">
        <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted pointer-events-none" />
        <input
          type="text"
          placeholder="Search file path…"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          className="h-8 w-full pl-7 pr-7 text-xs rounded-md bg-canvas-subtle border border-border text-fg placeholder-fg-subtle focus:outline-none focus:border-accent"
        />
        {query && (
          <button onClick={clear} className="absolute right-2 top-1/2 -translate-y-1/2 text-fg-muted hover:text-fg">
            <X size={12} />
          </button>
        )}
      </div>

      {open && filtered.length > 0 && (
        <div className="absolute z-50 mt-1 w-full max-h-64 overflow-y-auto rounded-md border border-border bg-canvas shadow-lg">
          {filtered.map((f) => (
            <button
              key={f}
              onMouseDown={() => select(f)}
              className={`w-full px-3 py-2 text-left text-xs font-mono truncate hover:bg-border-muted/40 transition-colors ${f === value ? 'text-accent bg-accent/5' : 'text-fg'}`}
            >
              {f}
            </button>
          ))}
          {fileList.length > 50 && (
            <div className="px-3 py-1.5 text-xs text-fg-muted border-t border-border">
              Showing 50 of {fileList.length} — type to narrow results
            </div>
          )}
        </div>
      )}
    </div>
  )
}

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend)

export default function DebtTimeline() {
  const { repos, repoId, setRepoId } = useRepoId()
  const handleRepoChange = (id) => {
    setRepoId(id)
    setFilePath('')
  }

  const repoFullName = repos.find((r) => r.id === repoId)?.full_name || ''
  const ghCommitUrl = (sha) => repoFullName && sha ? `https://github.com/${repoFullName}/commit/${sha}` : null

  const location = useLocation()
  const [filePath, setFilePath] = useState(location.state?.filePath || '')

  // Re-run every navigation to this page — location.key is unique per visit
  useEffect(() => {
    if (location.state?.filePath) {
      setFilePath(location.state.filePath)
    }
  }, [location.key])

  const { data, isLoading } = useQuery({
    queryKey: ['debt-timeline', repoId, filePath],
    queryFn: () => api.get(`/dashboard/${repoId}/debt/timeline/`, { params: { file_path: filePath || undefined } }).then((r) => r.data),
    enabled: !!repoId,
  })

  const d = data?.data
  const timeline = d?.timeline || []
  const fileList = d?.file_list || []

  // Once file_list loads, if no file is selected pick the first one
  useEffect(() => {
    if (!filePath && fileList.length > 0) setFilePath(fileList[0])
  }, [fileList])

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
        {/* Searchable file selector */}
        <div className="mb-4 flex items-center gap-3 flex-wrap">
          <FileSearch fileList={fileList} value={filePath} onChange={setFilePath} />
          {inflectionPoints.length > 0 && (
            <span className="text-xs text-danger">
              {inflectionPoints.length} inflection point{inflectionPoints.length !== 1 ? 's' : ''} detected
            </span>
          )}
        </div>

        {timeline.length === 0
          ? <div className="text-center py-20 text-fg-muted text-sm">
              {fileList.length === 0 ? 'No debt data yet — run an analysis first.' : 'No debt data for this file yet.'}
            </div>
          : <>
              <div className="rounded-lg border border-border bg-canvas-subtle p-4 mb-6">
                <div className="h-64">
                  <Line data={chartData} options={options} />
                </div>
              </div>

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
