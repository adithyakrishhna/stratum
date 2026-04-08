import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Activity, RotateCcw, X } from 'lucide-react'

import api from '../services/api'
import PageHeader from '../components/PageHeader'
import { RepoSelector, useRepos } from '../components/RepoSelector'
import { useWebSocket } from '../hooks/useWebSocket'

const STAGE_ORDER = ['ingestion', 'parsing', 'embedding', 'storage', 'intelligence']

function StageBadge({ status }) {
  const c = {
    completed: 'bg-success-subtle text-success',
    started:   'bg-accent/10 text-accent animate-pulse',
    failed:    'bg-danger-subtle text-danger',
    skipped:   'bg-border-muted text-fg-muted',
  }
  return <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${c[status] || 'bg-border-muted text-fg-muted'}`}>{status}</span>
}

function StageRow({ event }) {
  const durationSec = event.duration_ms ? (event.duration_ms / 1000).toFixed(1) : null
  return (
    <div className="flex items-center gap-3 py-3 border-b border-border-muted last:border-0">
      <div className="w-2 h-2 rounded-full shrink-0"
        style={{ backgroundColor: event.status === 'completed' ? '#3fb950' : event.status === 'failed' ? '#f85149' : event.status === 'started' ? '#58a6ff' : '#6e7681' }}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm text-fg font-medium capitalize">{event.stage}</span>
          <StageBadge status={event.status} />
        </div>
        {event.error_message && (
          <div className="text-xs text-danger mt-0.5 truncate">{event.error_message}</div>
        )}
      </div>
      {event.items_processed > 0 && (
        <span className="text-xs text-fg-muted shrink-0">{event.items_processed} items</span>
      )}
      {durationSec && (
        <span className="text-xs text-fg-subtle shrink-0">{durationSec}s</span>
      )}
      <span className="text-xs text-fg-subtle shrink-0 hidden md:block">
        {new Date(event.created_at).toLocaleTimeString()}
      </span>
    </div>
  )
}

export default function PipelineMonitor() {
  const { data: reposData } = useRepos()
  const repos = reposData?.data || []
  const stored = localStorage.getItem('stratum_repo_id')
  const ids = repos.map((r) => r.id)
  const [repoId, setRepoId] = useState(ids.includes(stored) ? stored : (ids[0] || null))
  const handleRepoChange = (id) => { localStorage.setItem('stratum_repo_id', id); setRepoId(id) }

  const [liveEvents, setLiveEvents] = useState([])
  useWebSocket(repoId, (msg) => setLiveEvents((prev) => [msg, ...prev].slice(0, 20)))

  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['pipeline', repoId],
    queryFn: () => api.get(`/dashboard/${repoId}/pipeline/`).then((r) => r.data),
    enabled: !!repoId,
    refetchInterval: 15_000,
  })

  const retryMutation = useMutation({
    mutationFn: (taskId) => api.post(`/dashboard/${repoId}/failed-tasks/${taskId}/retry/`),
    onSuccess: () => qc.invalidateQueries(['pipeline', repoId]),
  })

  const dismissMutation = useMutation({
    mutationFn: (taskId) => api.post(`/dashboard/${repoId}/failed-tasks/${taskId}/dismiss/`),
    onSuccess: () => qc.invalidateQueries(['pipeline', repoId]),
  })

  const d = data?.data
  const events = d?.events || []
  const failedTasks = d?.failed_tasks || []
  const allEvents = liveEvents.length ? liveEvents : events

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8 max-w-6xl mx-auto w-full">
      <PageHeader
        icon={Activity}
        title="Pipeline Monitor"
        subtitle="Live ingestion pipeline — stage events via WebSocket, failed tasks with retry/dismiss."
        right={<RepoSelector value={repoId} onChange={handleRepoChange} />}
      />

      {!repoId && <div className="text-center py-20 text-fg-muted text-sm">Select a repository.</div>}
      {repoId && isLoading && <div className="flex justify-center py-20"><div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>}

      {!isLoading && repoId && <>
        {d?.analysis_status && (
          <div className="mb-4 flex items-center gap-2">
            <span className="text-sm text-fg-muted">Analysis status:</span>
            <span className={`text-sm font-medium ${d.analysis_status === 'running' ? 'text-accent' : d.analysis_status === 'completed' ? 'text-success' : d.analysis_status === 'failed' ? 'text-danger' : 'text-fg-muted'}`}>
              {d.analysis_status}
            </span>
            {d.analysis_status === 'running' && (
              <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
            )}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Pipeline event log */}
          <div className="lg:col-span-2 rounded-lg border border-border bg-canvas-subtle p-4">
            <div className="text-sm font-medium text-fg mb-3 flex items-center gap-2">
              Pipeline Events
              {liveEvents.length > 0 && <span className="w-2 h-2 rounded-full bg-success animate-pulse" />}
            </div>

            {allEvents.length === 0
              ? <p className="text-sm text-fg-muted py-4 text-center">No pipeline events yet — trigger an analysis to begin.</p>
              : <div className="max-h-96 overflow-y-auto">
                  {allEvents.map((e) => <StageRow key={e.id || e.stage + e.created_at} event={e} />)}
                </div>
            }
          </div>

          {/* Failed tasks */}
          <div className="rounded-lg border border-border bg-canvas-subtle p-4">
            <div className="text-sm font-medium text-fg mb-3 flex items-center gap-2">
              Failed Tasks
              {failedTasks.length > 0 && (
                <span className="px-1.5 py-0.5 rounded bg-danger-subtle text-danger text-xs">{failedTasks.length}</span>
              )}
            </div>

            {failedTasks.length === 0
              ? <p className="text-sm text-fg-muted text-center py-4">No failed tasks.</p>
              : <div className="space-y-3">
                  {failedTasks.map((ft) => (
                    <div key={ft.id} className="rounded-md border border-danger/30 bg-danger-subtle/10 p-3">
                      <div className="text-xs font-mono text-fg mb-1">{ft.task_name.split('.').pop()}</div>
                      <div className="text-xs text-danger mb-2 line-clamp-2">{ft.error_message}</div>
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-fg-muted">Retried {ft.retry_count}×</span>
                        <div className="flex gap-1.5">
                          <button
                            onClick={() => retryMutation.mutate(ft.id)}
                            disabled={retryMutation.isLoading}
                            className="flex items-center gap-1 px-2 py-1 rounded text-xs border border-accent/40 text-accent hover:bg-accent/10 transition-colors disabled:opacity-50"
                          >
                            <RotateCcw size={11} /> Retry
                          </button>
                          <button
                            onClick={() => dismissMutation.mutate(ft.id)}
                            disabled={dismissMutation.isLoading}
                            className="flex items-center gap-1 px-2 py-1 rounded text-xs border border-border text-fg-muted hover:text-danger hover:border-danger/40 transition-colors disabled:opacity-50"
                          >
                            <X size={11} /> Dismiss
                          </button>
                        </div>
                      </div>
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
