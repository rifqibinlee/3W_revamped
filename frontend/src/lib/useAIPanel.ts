import { useContext } from 'react'
import { AIPanelContext, type AIPanelContextValue } from './aiPanelContext'

export function useAIPanel(): AIPanelContextValue {
  const ctx = useContext(AIPanelContext)
  if (!ctx) throw new Error('useAIPanel must be used within an AIPanelProvider')
  return ctx
}
