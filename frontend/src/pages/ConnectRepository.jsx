import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { GitFork, Plus, Trash2, Play, CheckCircle, AlertCircle, Loader, GitBranch, RefreshCw } from 'lucide-react'

import api from '../services/api'
import PageHeader from '../components/PageHeader'

function StatusBadge({ status }) {
  const map = {
    pending:   { color: 'text-fg-muted bg-border-muted',           label: 'Pending' },
    running:   { color: 'text-accent bg-accent/10 animate-pulse',  label: 'Analyzing…' },
    completed: { color: 'text-success bg-success-subtle',          label: 'Analyzed' },
    failed:    { color: 'text-danger bg-danger-subtle',            label: 'Failed' },
  }
  const { color, label } = map[status] || map.pending
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${color}`}>
      {label}
    </span>
  )
}

function BranchSelect({ repo, value, onChange }) {
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['branches', repo.id],
    queryFn: () => api.get(`/repositories/${repo.id}/branches/`).then(r => r.data),
    staleTime: 60_000,          // refetch after 1 min
    refetchInterval: 60_000,    // poll every 60s for real-time updates
    refetchOnWindowFocus: true,
  })

  const branches = data?.data || []
  // Always include the currently-selected branch even if API is slow/failed
  const options = branches.includes(value) ? branches : [value, ...branches].filter(Boolean)

  return (
    <div className="flex items-center gap-1.5 flex-1 min-w-0">
      <GitBranch size={13} className="text-fg-muted shrink-0" />
      <div className="relative">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={isLoading}
          className="h-7 pl-2 pr-6 text-xs font-mono rounded bg-canvas border border-border text-fg
                     focus:outline-none focus:border-accent appearance-none cursor-pointer
                     disabled:opacity-50 min-w-[9rem]"
        >
          {isLoading && <option disabled value="">Loading…</option>}
          {options.map(b => (
            <option key={b} value={b}>{b}</option>
          ))}
        </select>
        {/* custom caret */}
        <span className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-fg-muted">
          ▾
        </span>
      </div>
      <button
        onClick={() => refetch()}
        title="Refresh branches"
        disabled={isFetching}
        className="flex items-center justify-center w-5 h-5 text-fg-muted hover:text-fg
                   transition-colors disabled:opacity-40"
      >
        <RefreshCw size={11} className={isFetching ? 'animate-spin' : ''} />
      </button>
      {isError && (
        <span className="text-xs text-warning">couldn't fetch branches</span>
      )}
    </div>
  )
}

function RepoRow({ repo, onAnalyze, onDisconnect, analyzing, disconnecting }) {
  const [branch, setBranch] = useState(repo.default_branch || 'main')
  const branchChanged = branch !== repo.default_branch

  return (
    <div className="px-4 py-4 border-b border-border-muted last:border-0">
      {/* Top row: name + status + disconnect */}
      <div className="flex items-center gap-3 mb-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-fg text-sm">{repo.full_name}</span>
            {repo.is_private && (
              <span className="px-1.5 py-0.5 rounded text-xs border border-border text-fg-muted">private</span>
            )}
            <StatusBadge status={repo.analysis_status} />
          </div>
        </div>
        <button
          onClick={() => {
            if (confirm(`Disconnect ${repo.full_name}? This removes your access but keeps the data.`)) {
              onDisconnect(repo.id)
            }
          }}
          disabled={disconnecting}
          title="Disconnect"
          className="flex items-center justify-center w-7 h-7 rounded border border-border
                     text-fg-muted hover:text-danger hover:border-danger/40 transition-colors
                     disabled:opacity-40"
        >
          <Trash2 size={13} />
        </button>
      </div>

      {/* Bottom row: branch dropdown + analyze button */}
      <div className="flex items-center gap-2">
        <BranchSelect repo={repo} value={branch} onChange={setBranch} />
        {branchChanged && (
          <span className="text-xs text-warning shrink-0">will re-analyze from scratch</span>
        )}

        <button
          onClick={() => onAnalyze(repo.id, branch)}
          disabled={analyzing || repo.analysis_status === 'running'}
          className="flex items-center gap-1.5 px-3 h-7 rounded text-xs border border-accent/40
                     text-accent hover:bg-accent/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
        >
          {analyzing
            ? <Loader size={12} className="animate-spin" />
            : <Play size={12} />
          }
          {repo.analysis_status === 'completed' ? 'Re-analyze' : 'Analyze'}
        </button>
      </div>
    </div>
  )
}

export default function ConnectRepository() {
  const qc = useQueryClient()
  const [input, setInput] = useState('')
  const [feedback, setFeedback] = useState(null)
  const [analyzingId, setAnalyzingId] = useState(null)

  const { data: reposData, isLoading: reposLoading } = useQuery({
    queryKey: ['repos'],
    queryFn: () => api.get('/repositories/').then((r) => r.data),
    // Poll every 3s while any repo is still running so the status badge updates automatically.
    // Returns false when nothing is running to avoid unnecessary requests.
    refetchInterval: (query) => {
      const repos = query.state.data?.data || []
      return repos.some((r) => r.analysis_status === 'running') ? 3_000 : false
    },
  })
  const repos = reposData?.data || []

  const connectMutation = useMutation({
    mutationFn: (full_name) => api.post('/repositories/connect/', { full_name }),
    onSuccess: (res) => {
      const already = res.data?.meta?.already_connected
      setFeedback({
        type: 'success',
        message: already
          ? `${res.data.data.full_name} is already connected.`
          : `Connected ${res.data.data.full_name}. Now select a branch and click Analyze.`,
      })
      setInput('')
      qc.invalidateQueries(['repos'])
    },
    onError: (err) => {
      setFeedback({ type: 'error', message: err.response?.data?.error || 'Failed to connect repository.' })
    },
  })

  const analyzeMutation = useMutation({
    mutationFn: ({ repoId, branch }) => api.post(`/repositories/${repoId}/analyze/`, { branch }),
    onSuccess: () => {
      setFeedback({ type: 'success', message: 'Analysis queued. Check Pipeline Monitor for progress.' })
      setAnalyzingId(null)
      qc.invalidateQueries(['repos'])
    },
    onError: (err) => {
      setFeedback({ type: 'error', message: err.response?.data?.error || 'Failed to start analysis.' })
      setAnalyzingId(null)
    },
  })

  const disconnectMutation = useMutation({
    mutationFn: (repoId) => api.post(`/repositories/${repoId}/disconnect/`),
    onSuccess: () => qc.invalidateQueries(['repos']),
  })

  const handleConnect = (e) => {
    e.preventDefault()
    setFeedback(null)
    const clean = input.trim()
      .replace('https://github.com/', '')
      .replace('http://github.com/', '')
      .replace(/\.git$/, '')
      .trim()
    if (!clean) return
    connectMutation.mutate(clean)
  }

  const handleAnalyze = (repoId, branch) => {
    setFeedback(null)
    setAnalyzingId(repoId)
    analyzeMutation.mutate({ repoId, branch })
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8 max-w-3xl mx-auto w-full">
      <PageHeader
        icon={GitFork}
        title="Connect Repository"
        subtitle="Add a GitHub repository, pick a branch, then analyze to start tracking debt."
      />

      {/* Connect form */}
      <div className="rounded-lg border border-border bg-canvas-subtle p-5 mb-6">
        <div className="text-sm font-medium text-fg mb-3">Add a repository</div>
        <form onSubmit={handleConnect} className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="owner/repo  or  https://github.com/owner/repo"
            className="flex-1 h-9 px-3 text-sm rounded-md bg-canvas border border-border text-fg
                       placeholder:text-fg-subtle focus:outline-none focus:border-accent"
            disabled={connectMutation.isLoading}
          />
          <button
            type="submit"
            disabled={connectMutation.isLoading || !input.trim()}
            className="flex items-center gap-1.5 px-4 h-9 rounded-md text-sm font-medium
                       bg-accent text-canvas hover:bg-accent-emphasis transition-colors
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {connectMutation.isLoading ? <Loader size={14} className="animate-spin" /> : <Plus size={14} />}
            Connect
          </button>
        </form>
        <p className="text-xs text-fg-muted mt-2">
          Public repos work instantly. Private repos require a <code className="text-fg">GITHUB_PERSONAL_ACCESS_TOKEN</code> in your <code className="text-fg">.env</code>.
        </p>

        {feedback && (
          <div className={`mt-3 flex items-start gap-2 text-sm px-3 py-2 rounded-md ${feedback.type === 'success' ? 'bg-success-subtle text-success' : 'bg-danger-subtle text-danger'}`}>
            {feedback.type === 'success' ? <CheckCircle size={15} className="shrink-0 mt-0.5" /> : <AlertCircle size={15} className="shrink-0 mt-0.5" />}
            {feedback.message}
          </div>
        )}
      </div>

      {/* Connected repos */}
      <div className="rounded-lg border border-border overflow-hidden">
        <div className="px-4 py-3 bg-canvas-subtle border-b border-border flex items-center justify-between">
          <span className="text-sm font-medium text-fg">Connected Repositories</span>
          <span className="text-xs text-fg-muted">{repos.length} repo{repos.length !== 1 ? 's' : ''}</span>
        </div>

        {reposLoading && (
          <div className="flex justify-center py-8">
            <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        {!reposLoading && repos.length === 0 && (
          <div className="text-center py-10 text-fg-muted text-sm">No repositories connected yet. Add one above.</div>
        )}

        {repos.map((repo) => (
          <RepoRow
            key={repo.id}
            repo={repo}
            onAnalyze={handleAnalyze}
            onDisconnect={disconnectMutation.mutate}
            analyzing={analyzingId === repo.id && analyzeMutation.isLoading}
            disconnecting={disconnectMutation.isLoading}
          />
        ))}
      </div>
    </div>
  )
}
