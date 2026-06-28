import { useEffect, useState } from 'react'
import { DataTable, type Column } from '../components/DataTable'
import { GlassPanel } from '../components/GlassPanel'
import { api, ApiError, type LoginHistoryEntry, type UserOut } from '../lib/api'
import { useAuth } from '../lib/useAuth'

export function SuperAdmin() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState<UserOut[]>([])
  const [history, setHistory] = useState<LoginHistoryEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [passwordDrafts, setPasswordDrafts] = useState<Record<string, string>>({})

  function load() {
    api.listUsers().then(setUsers).catch(() => setError('Could not load users'))
    api.loginHistory().then(setHistory).catch(() => setError('Could not load login history'))
  }

  useEffect(load, [])

  async function handleSetPassword(userId: string) {
    const newPassword = passwordDrafts[userId]?.trim()
    if (!newPassword || newPassword.length < 8) {
      setError('New password must be at least 8 characters')
      return
    }
    try {
      await api.setUserPassword(userId, newPassword)
      setPasswordDrafts((prev) => ({ ...prev, [userId]: '' }))
      setStatus('Password updated')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not set password')
    }
  }

  async function handleDeleteUser(userId: string, username: string) {
    if (!window.confirm(`Delete user "${username}"? This cannot be undone.`)) return
    try {
      await api.deleteUser(userId)
      setStatus(`Deleted ${username}`)
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not delete user')
    }
  }

  const userColumns: Column<UserOut>[] = [
    { key: 'username', label: 'Username' },
    { key: 'email', label: 'Email' },
    {
      key: 'role',
      label: 'Role',
      render: (u) => (
        <span
          className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
            u.role === 'super_admin' ? 'bg-accent-400/20 text-accent-300' : 'bg-white/10 text-white/70'
          }`}
        >
          {u.role}
        </span>
      ),
    },
    {
      key: 'password',
      label: 'Reset password',
      render: (u) => (
        <div className="flex gap-1.5">
          <input
            type="password"
            value={passwordDrafts[u.id] ?? ''}
            onChange={(e) => setPasswordDrafts((prev) => ({ ...prev, [u.id]: e.target.value }))}
            placeholder="New password"
            className="w-32 rounded-lg border border-white/15 bg-white/5 px-2 py-1 text-xs focus:border-sky-400/60 focus:outline-none"
          />
          <button
            onClick={() => handleSetPassword(u.id)}
            className="rounded-lg border border-white/20 px-2 py-1 text-xs font-semibold text-white/80 hover:bg-white/10"
          >
            Set
          </button>
        </div>
      ),
    },
    {
      key: 'actions',
      label: '',
      render: (u) =>
        u.id === me?.id ? null : (
          <button
            onClick={() => handleDeleteUser(u.id, u.username)}
            className="rounded-lg border border-red-400/30 px-2 py-1 text-xs font-semibold text-red-300 hover:bg-red-400/10"
          >
            Delete
          </button>
        ),
    },
  ]

  const historyColumns: Column<LoginHistoryEntry>[] = [
    { key: 'username', label: 'User' },
    { key: 'ip_address', label: 'IP address' },
    { key: 'logged_in_at', label: 'Logged in at', render: (h) => new Date(h.logged_in_at).toLocaleString() },
  ]

  return (
    <div className="space-y-4">
      <GlassPanel>
        <p className="mb-1 font-display text-lg font-semibold">Super Admin</p>
        <p className="text-sm text-white/55">
          Manage users, review login activity, and moderate content across the platform. Annotations, projects, and
          chat messages can be deleted from their own pages — those actions only appear for Super Admins.
        </p>
        {error && <p className="mt-3 text-sm text-red-300">{error}</p>}
        {status && <p className="mt-3 text-sm text-emerald-300">{status}</p>}
      </GlassPanel>

      <GlassPanel>
        <p className="mb-3.5 font-display text-sm font-semibold">Users ({users.length})</p>
        <DataTable columns={userColumns} rows={users} emptyMessage="No users yet." />
      </GlassPanel>

      <GlassPanel>
        <p className="mb-3.5 font-display text-sm font-semibold">Login history ({history.length})</p>
        <div className="max-h-96 overflow-y-auto">
          <DataTable columns={historyColumns} rows={history} emptyMessage="No login activity yet." />
        </div>
      </GlassPanel>
    </div>
  )
}
