import { Layers } from 'lucide-react'
import { PageShell } from './Overview'

export default function ClusterMap() {
  return (
    <PageShell
      icon={Layers}
      title="Semantic Cluster Map"
      subtitle="Bubble chart of recurring code patterns — size = files affected, color = growth rate. Timeline slider shows cluster evolution."
      badges={[
        'Bubble chart (Chart.js)',
        'Timeline slider (git history)',
        'Cluster detail panel on click',
        'Growth rate color scale',
        'Language filter',
        'Flagged clusters highlight',
      ]}
    />
  )
}
