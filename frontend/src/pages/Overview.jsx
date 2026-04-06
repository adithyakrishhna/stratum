import { LayoutDashboard } from 'lucide-react'

function PageShell({ icon: Icon, title, subtitle, badges = [] }) {
  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8 max-w-6xl mx-auto w-full">
      <div className="flex items-center gap-3 mb-1">
        <Icon size={20} className="text-accent shrink-0" strokeWidth={1.5} />
        <h1 className="text-lg sm:text-xl font-semibold text-fg">{title}</h1>
      </div>
      <p className="text-fg-muted text-sm mb-6 ml-8">{subtitle}</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
        {badges.map((b) => (
          <div key={b} className="rounded-lg border border-border bg-canvas-subtle p-4 text-fg-subtle text-sm">
            {b}
          </div>
        ))}
      </div>
    </div>
  )
}

export { PageShell }

function Overview() {
  return (
    <PageShell
      icon={LayoutDashboard}
      title="Repository Overview"
      subtitle="Health score, debt trend, top deteriorating files, and live analysis progress."
      badges={[
        'Health score gauge',
        'Debt trend chart (30 days)',
        'Top 5 deteriorating files',
        'Spreading pattern count',
        'Live analysis progress bar',
        'Recent PR findings summary',
      ]}
    />
  )
}

export default Overview
