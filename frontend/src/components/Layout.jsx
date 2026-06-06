import { useState, useEffect } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  LayoutDashboard, GitPullRequest, TrendingUp, Layers,
  Flame, GitCommit, Activity, LogOut, Hexagon, Menu, X, GitFork,
} from 'lucide-react'
import api from '../services/api'

const NAV = [
  { to: '/dashboard',          icon: LayoutDashboard, label: 'Overview' },
  { to: '/dashboard/pr',       icon: GitPullRequest,  label: 'PR Review' },
  { to: '/dashboard/debt',     icon: TrendingUp,      label: 'Debt Timeline' },
  { to: '/dashboard/clusters', icon: Layers,          label: 'Cluster Map' },
  { to: '/dashboard/heatmap',  icon: Flame,           label: 'Velocity Heatmap' },
  { to: '/dashboard/blame',    icon: GitCommit,       label: 'Blame Report' },
  { to: '/dashboard/pipeline', icon: Activity,        label: 'Pipeline Monitor' },
  { to: '/dashboard/connect',  icon: GitFork,         label: 'Connect Repo', divider: true },
]

function Sidebar({ open, onClose, user, onLogout }) {
  return (
    <>
      {/* Mobile overlay backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-20 bg-black/60 lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar panel */}
      <aside
        className={`
          fixed inset-y-0 left-0 z-30 flex flex-col w-60
          bg-canvas-subtle border-r border-border
          transition-transform duration-200 ease-in-out
          lg:static lg:translate-x-0 lg:z-auto
          ${open ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        {/* Logo + mobile close */}
        <div className="flex items-center justify-between px-4 py-5 border-b border-border">
          <div className="flex items-center gap-2">
            <Hexagon size={20} className="text-accent" strokeWidth={1.5} />
            <span className="font-semibold text-fg text-[15px] tracking-tight">Stratum</span>
          </div>
          <button
            onClick={onClose}
            className="lg:hidden p-1 rounded text-fg-muted hover:text-fg"
          >
            <X size={18} />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto py-3 px-2">
          {NAV.map(({ to, icon: Icon, label, divider }) => (
            <div key={to}>
              {divider && <div className="my-2 border-t border-border-muted" />}
            <NavLink
              to={to}
              end={to === '/dashboard'}
              onClick={onClose}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-md text-sm mb-0.5 transition-colors ${
                  isActive
                    ? 'bg-accent/10 text-accent font-medium'
                    : 'text-fg-muted hover:text-fg hover:bg-border-muted'
                }`
              }
            >
              <Icon size={16} strokeWidth={1.75} />
              {label}
            </NavLink>
            </div>
          ))}
        </nav>

        {/* User + logout */}
        <div className="px-3 py-4 border-t border-border">
          <div className="flex items-center gap-2.5 px-1 mb-2">
            {user?.avatar_url
              ? <img src={user.avatar_url} alt="" className="w-6 h-6 rounded-full shrink-0" />
              : <div className="w-6 h-6 rounded-full bg-accent/20 flex items-center justify-center shrink-0">
                  <span className="text-[10px] font-medium text-accent">
                    {(user?.display_name || '?')[0].toUpperCase()}
                  </span>
                </div>
            }
            <span className="text-xs text-fg-muted truncate">
              {user?.display_name || '—'}
            </span>
          </div>
          <button
            onClick={onLogout}
            className="flex items-center gap-2 w-full px-3 py-2 rounded-md text-sm
                       text-fg-muted hover:text-danger hover:bg-danger-subtle transition-colors"
          >
            <LogOut size={14} />
            Sign out
          </button>
        </div>
      </aside>
    </>
  )
}

function Layout({ children }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()

  // Close sidebar on route change (mobile)
  useEffect(() => { setSidebarOpen(false) }, [location.pathname])

  const { data } = useQuery({
    queryKey: ['currentUser'],
    queryFn: () => api.get('/repositories/me/').then((r) => r.data),
  })

  const handleLogout = () => {
    const form = document.createElement('form')
    form.method = 'POST'
    form.action = '/accounts/logout/'
    const csrf = document.createElement('input')
    csrf.type = 'hidden'
    csrf.name = 'csrfmiddlewaretoken'
    csrf.value = document.cookie.split('; ').find(c => c.startsWith('csrftoken='))?.split('=')[1] || ''
    form.appendChild(csrf)
    document.body.appendChild(form)
    form.submit()
  }

  const currentPage = NAV.find(n =>
    n.to === '/dashboard'
      ? location.pathname === '/dashboard'
      : location.pathname.startsWith(n.to)
  )

  return (
    <div className="flex h-screen bg-canvas overflow-hidden">
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        user={data?.data}
        onLogout={handleLogout}
      />

      {/* Content area */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Mobile top bar */}
        <header className="lg:hidden flex items-center gap-3 px-4 py-3 border-b border-border bg-canvas-subtle shrink-0">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-1.5 rounded-md text-fg-muted hover:text-fg hover:bg-border-muted transition-colors"
            aria-label="Open menu"
          >
            <Menu size={20} />
          </button>
          <div className="flex items-center gap-2">
            <Hexagon size={17} className="text-accent" strokeWidth={1.5} />
            <span className="font-semibold text-fg text-sm tracking-tight">Stratum</span>
          </div>
          {currentPage && (
            <span className="ml-auto text-sm text-fg-muted">{currentPage.label}</span>
          )}
        </header>

        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  )
}

export default Layout
