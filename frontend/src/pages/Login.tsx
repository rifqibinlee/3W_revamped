import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatedBackground } from '../components/AnimatedBackground'
import { GlassPanel } from '../components/GlassPanel'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/useAuth'

export function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(username, password)
      navigate('/')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not sign in')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center">
      <AnimatedBackground />
      <GlassPanel className="relative w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-accent-400 to-sky-500 font-display text-sm font-bold text-ink-900">
            3W
          </div>
          <span className="font-display text-lg font-semibold">3W ops</span>
        </div>
        <h1 className="mb-1 font-display text-2xl font-semibold">Sign in</h1>
        <p className="mb-6 text-sm text-white/60">Network operations dashboard</p>

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="text"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            className="w-full rounded-2xl border border-white/15 bg-white/5 px-4 py-2.5 text-sm placeholder:text-white/40 focus:border-sky-400/60 focus:outline-none"
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="w-full rounded-2xl border border-white/15 bg-white/5 px-4 py-2.5 text-sm placeholder:text-white/40 focus:border-sky-400/60 focus:outline-none"
          />
          {error && <p className="text-sm text-red-300">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-2xl bg-gradient-to-r from-accent-400 to-accent-500 py-2.5 font-display text-sm font-semibold text-ink-900 disabled:opacity-60"
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </GlassPanel>
    </div>
  )
}
