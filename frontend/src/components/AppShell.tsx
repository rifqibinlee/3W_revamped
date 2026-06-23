import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { useAuth } from '../lib/useAuth'
import { AnimatedBackground } from './AnimatedBackground'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard' },
  { to: '/map', label: 'Map' },
  { to: '/notes', label: 'Notes' },
  { to: '/projects', label: 'Projects' },
  { to: '/chat', label: 'Chat' },
  { to: '/pricing', label: 'CAPEX' },
  { to: '/agent', label: 'Agent' },
]

const ADMIN_NAV_ITEMS = [{ to: '/data', label: 'Data' }]

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const initials = user?.username.slice(0, 2).toUpperCase() ?? '--'
  const navItems = user?.role === 'admin' ? [...NAV_ITEMS, ...ADMIN_NAV_ITEMS] : NAV_ITEMS

  return (
    <div className="relative min-h-screen">
      <AnimatedBackground />
      <div className="relative mx-auto max-w-6xl px-7 py-6">
        <header className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-accent-400 to-sky-500 font-display text-sm font-bold text-ink-900">
              3W
            </div>
            <span className="font-display text-base font-semibold">3W ops</span>
          </div>
          <nav className="flex items-center gap-6 text-sm text-white/75">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => (isActive ? 'font-medium text-white' : '')}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <button
            type="button"
            onClick={logout}
            title="Sign out"
            className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-accent-400 to-accent-500 font-display text-xs font-semibold text-ink-900"
          >
            {initials}
          </button>
        </header>
        <main>{children}</main>
      </div>
    </div>
  )
}
