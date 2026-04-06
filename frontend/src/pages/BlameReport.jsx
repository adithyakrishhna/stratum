import { GitCommit } from 'lucide-react'
import { PageShell } from './Overview'

export default function BlameReport() {
  return (
    <PageShell
      icon={GitCommit}
      title="Blame Report"
      subtitle="Commits ranked by debt introduced — not by lines changed, but by patterns originated and spread."
      badges={[
        'Commits table (debt score desc)',
        'Author, date, SHA columns',
        'Patterns originated count',
        'Files eventually affected',
        'Click → patterns introduced',
        'Export CSV',
      ]}
    />
  )
}
