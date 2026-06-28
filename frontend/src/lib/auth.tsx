import { useEffect, useState, type ReactNode } from 'react'
import { api, setToken, type UserOut } from './api'
import { AuthContext } from './authContext'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  async function login(username: string, password: string) {
    const tokens = await api.login(username, password)
    setToken(tokens.access_token)
    const me = await api.me()
    setUser(me)
  }

  function logout() {
    setToken(null)
    setUser(null)
  }

  async function refreshUser() {
    const me = await api.me()
    setUser(me)
  }

  return <AuthContext.Provider value={{ user, loading, login, logout, refreshUser }}>{children}</AuthContext.Provider>
}
