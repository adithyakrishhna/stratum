/** Small metric card used on Overview and PR pages. */
export default function StatCard({ label, value, sub, color = 'text-fg' }) {
  return (
    <div className="rounded-lg border border-border bg-canvas-subtle p-4">
      <div className="text-xs text-fg-muted mb-1">{label}</div>
      <div className={`text-2xl font-semibold ${color}`}>{value ?? '—'}</div>
      {sub && <div className="text-xs text-fg-subtle mt-1">{sub}</div>}
    </div>
  )
}
