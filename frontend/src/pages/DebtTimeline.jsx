import { TrendingUp } from 'lucide-react'
import { PageShell } from './Overview'

export default function DebtTimeline() {
  return (
    <PageShell
      icon={TrendingUp}
      title="Debt Timeline"
      subtitle="File-level debt score plotted over every commit, with inflection point highlights and side-by-side comparison."
      badges={[
        'File selector dropdown',
        'Debt score line chart (all commits)',
        'Commit message annotations on chart',
        'Inflection point markers',
        'Side-by-side file comparison',
        'Language filter',
      ]}
    />
  )
}
