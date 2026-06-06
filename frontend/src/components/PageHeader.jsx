/**
 * Standard page header: icon + title + subtitle + optional right slot.
 */
export default function PageHeader({ icon: Icon, title, subtitle, right }) {
  return (
    <div className="flex items-start justify-between mb-6">
      <div>
        <div className="flex items-center gap-2.5 mb-1">
          {Icon && <Icon size={20} className="text-accent shrink-0" strokeWidth={1.5} />}
          <h1 className="text-lg font-semibold text-fg">{title}</h1>
        </div>
        {subtitle && <p className="text-sm text-fg-muted ml-[28px]">{subtitle}</p>}
      </div>
      {right && <div className="shrink-0 ml-4">{right}</div>}
    </div>
  )
}
