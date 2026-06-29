import { useState, type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import logo from '../assets/3w-logo.png'
import { API_BASE_URL } from '../lib/api'
import { useAuth } from '../lib/useAuth'
import { AIPanel } from './AIPanel'
import { AnimatedBackground } from './AnimatedBackground'
import { ProfileSettings } from './ProfileSettings'

const NAV_ITEMS = [
  { to: '/', label: 'RAN Forecast' },
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
  const [menuOpen, setMenuOpen] = useState(false)
  const [profileMenuOpen, setProfileMenuOpen] = useState(false)
  const [profileSettingsOpen, setProfileSettingsOpen] = useState(false)
  const initials = user?.username.slice(0, 2).toUpperCase() ?? '--'
  const navItems = [
    ...NAV_ITEMS,
    ...(user?.role === 'admin' || user?.role === 'super_admin' ? ADMIN_NAV_ITEMS : []),
    ...(user?.role === 'super_admin' ? SUPER_ADMIN_NAV_ITEMS : []),
  ]

  return (
    <div className="relative min-h-screen pb-9">
      <AnimatedBackground />
      <div className="relative mx-auto max-w-[1600px] px-4 py-4 sm:px-7 sm:py-6">
        <header className="mb-6 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <img src={logo} alt="3W+" className="h-8 w-8" />
            <span className="font-display text-base font-semibold">3W+</span>
          </div>

          {/* Desktop/tablet nav — hidden on small screens in favor of the hamburger menu */}
          <nav className="hidden flex-wrap items-center gap-x-5 gap-y-1 text-sm text-white/75 md:flex">
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

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              title="Menu"
              className="flex h-8 w-8 items-center justify-center rounded-lg text-white/80 hover:bg-white/10 md:hidden"
            >
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                {menuOpen ? <path d="M6 6l12 12M18 6 6 18" /> : <path d="M4 6h16M4 12h16M4 18h16" />}
              </svg>
            </button>
            <div className="relative">
              <button
                type="button"
                onClick={() => setProfileMenuOpen((v) => !v)}
                title="Account"
                className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-gradient-to-br from-accent-400 to-accent-500 font-display text-xs font-semibold text-ink-900"
              >
                {user?.avatar_url ? (
                  <img src={`${API_BASE_URL}${user.avatar_url}`} alt="" className="h-full w-full object-cover" />
                ) : (
                  initials
                )}
              </button>
              {profileMenuOpen && (
                <div className="absolute right-0 top-full z-30 mt-2 w-44 rounded-2xl border border-white/15 bg-ink-900/95 p-1.5 text-sm backdrop-blur-xl">
                  <button
                    onClick={() => {
                      setProfileSettingsOpen(true)
                      setProfileMenuOpen(false)
                    }}
                    className="block w-full rounded-lg px-3 py-2 text-left text-white/80 hover:bg-white/10"
                  >
                    Profile settings
                  </button>
                  <button onClick={logout} className="block w-full rounded-lg px-3 py-2 text-left text-white/80 hover:bg-white/10">
                    Sign out
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        {profileSettingsOpen && <ProfileSettings onClose={() => setProfileSettingsOpen(false)} />}

        {/* Mobile/tablet dropdown nav */}
        {menuOpen && (
          <nav className="mb-6 -mt-3 flex flex-col gap-0.5 rounded-2xl border border-white/15 bg-ink-900/95 p-2 text-sm text-white/75 backdrop-blur-xl md:hidden">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setMenuOpen(false)}
                className={({ isActive }) => `rounded-lg px-3 py-2 ${isActive ? 'bg-white/10 font-medium text-white' : 'hover:bg-white/5'}`}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        )}

        <main>{children}</main>
      </div>
      <AIPanel />
      <p className="fixed inset-x-0 bottom-0 z-30 bg-ink-950/80 py-1.5 text-center text-[10px] text-white/45 backdrop-blur-sm">
        Brought to You by Advanced Analytics
      </p>
    </div>
  )
}
