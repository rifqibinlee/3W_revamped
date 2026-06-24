import { useState, type ReactNode } from 'react'
import { api, ApiError } from './api'
import { AIPanelContext, type ChatTurn } from './aiPanelContext'

// Holds chat history + open/closed state above AppShell (AppShell is
// re-instantiated per route in App.tsx, not a single persistent
// Outlet wrapper), so both survive page navigation — same reasoning
// as AuthProvider being mounted once in main.tsx rather than per page.
export function AIPanelProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function sendMessage(message: string) {
    if (!message.trim() || sending) return
    setTurns((prev) => [...prev, { role: 'user', content: message }])
    setSending(true)
    setError(null)
    try {
      const { reply } = await api.agentChat(message)
      setTurns((prev) => [...prev, { role: 'assistant', content: reply }])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The agent could not respond')
    } finally {
      setSending(false)
    }
  }

  return (
    <AIPanelContext.Provider value={{ open, setOpen, turns, sending, error, sendMessage }}>
      {children}
    </AIPanelContext.Provider>
  )
}
