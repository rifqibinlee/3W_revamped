import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import logo from '../assets/3w-logo.png'
import { useAuth } from '../lib/useAuth'
import { AIPanel } from './AIPanel'
import { AnimatedBackground } from './AnimatedBackground'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard' },
  { to: '/map', label: 'Map' },
  { to: '/notes', label: 'Notes' },
  { to: '/projects', label: 'Projects' },
  { to: '/chat', label: 'Chat' },
  { to: '/pricing', label: 'CAPEX' },
]

const ADMIN_NAV_ITEMS = [{ to: '/data', label: 'Data' }]
const SUPER_ADMIN_NAV_ITEMS = [{ to: '/admin', label: 'Super Admin' }]

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const initials = user?.username.slice(0, 2).toUpperCase() ?? '--'
  const navItems = [
    ...NAV_ITEMS,
    ...(user?.role === 'admin' || user?.role === 'super_admin' ? ADMIN_NAV_ITEMS : []),
    ...(user?.role === 'super_admin' ? SUPER_ADMIN_NAV_ITEMS : []),
  ]

  return (
    <div className="relative min-h-screen pb-9">
      <AnimatedBackground />
      <div className="relative mx-auto max-w-[1600px] px-7 py-6">
        <header className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <img src={logo} alt="3W+" className="h-8 w-8" />
            <span className="font-display text-base font-semibold">3W+</span>
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
      <AIPanel />
      <p className="fixed inset-x-0 bottom-0 z-30 bg-ink-950/80 py-1.5 text-center text-[10px] text-white/45 backdrop-blur-sm">
        Brought to You by Advanced Analytics
      </p>
    </div>
  )
}
