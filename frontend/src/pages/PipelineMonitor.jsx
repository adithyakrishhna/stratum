import { Activity } from 'lucide-react'
import { PageShell } from './Overview'

export default function PipelineMonitor() {
  return (
    <PageShell
      icon={Activity}
      title="Pipeline Monitor"
      subtitle="Live ingestion pipeline — stage progress via WebSocket, failed tasks with retry/dismiss."
      badges={[
        'Stage progress bars (live WebSocket)',
        'Items processed per stage',
        'Duration per stage',
        'Failed tasks list',
        'Retry / dismiss actions',
        'Pipeline history log',
      ]}
    />
  )
}
