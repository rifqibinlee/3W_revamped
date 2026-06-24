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
            <img src={logo} alt="3W+" className="h-8 w-8" />
            <div className="leading-tight">
              <span className="block font-display text-base font-semibold">3W+</span>
              <span className="block text-[10px] text-white/45">Brought to You by Advanced Analytics</span>
            </div>
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
    </div>
  )
}
