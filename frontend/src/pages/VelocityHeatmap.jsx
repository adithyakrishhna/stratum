import { Flame } from 'lucide-react'
import { PageShell } from './Overview'

export default function VelocityHeatmap() {
  return (
    <PageShell
      icon={Flame}
      title="Velocity Heatmap"
      subtitle="File tree colored by debt velocity — red = deteriorating fast, green = improving, grey = stable."
      badges={[
        'Interactive file tree',
        'Velocity color scale',
        'Language filter',
        'Directory filter',
        'Time range picker',
        'Click file → Debt Timeline',
      ]}
    />
  )
}
