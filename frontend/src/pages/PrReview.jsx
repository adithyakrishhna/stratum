import { GitPullRequest } from 'lucide-react'
import { PageShell } from './Overview'

export default function PrReview() {
  return (
    <PageShell
      icon={GitPullRequest}
      title="PR Review Center"
      subtitle="All pull requests, findings breakdown by severity, triggered rules, and debt impact score per PR."
      badges={[
        'PR list with status badges',
        'Findings by severity (Critical / High / Medium / Low)',
        'Security findings chart',
        'Rule violations per PR',
        'Debt impact score indicator',
        'Time-to-review metric',
      ]}
    />
  )
}
