import { createContext } from 'react'

export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}

export interface AIPanelContextValue {
  open: boolean
  setOpen: (open: boolean) => void
  turns: ChatTurn[]
  sending: boolean
  error: string | null
  sendMessage: (message: string) => Promise<void>
}

export const AIPanelContext = createContext<AIPanelContextValue | undefined>(undefined)
