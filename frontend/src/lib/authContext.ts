import { createContext } from 'react'
import type { UserOut } from './api'

export interface AuthContextValue {
  user: UserOut | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  refreshUser: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)
