import { useEffect, useRef, useState, type FormEvent } from 'react'
import { GlassPanel } from '../components/GlassPanel'
import { api, ApiError } from '../lib/api'

interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}

export function Agent() {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const message = input.trim()
    if (!message || sending) return
    setTurns((prev) => [...prev, { role: 'user', content: message }])
    setInput('')
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
    <div className="flex h-[75vh] flex-col">
      <GlassPanel className="flex flex-1 flex-col overflow-hidden">
        <p className="mb-3 font-display text-sm font-semibold">Network ops assistant</p>
        <div className="flex-1 space-y-3 overflow-y-auto pr-1">
          {turns.length === 0 && (
            <p className="text-sm text-white/50">
              Ask about congestion, CAPEX upgrades, or network KPIs — e.g. "Which sites in Central are congested?"
            </p>
          )}
          {turns.map((t, i) => (
            <div key={i} className={`flex ${t.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-lg rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap ${
                  t.role === 'user' ? 'bg-gradient-to-r from-sky-400 to-sky-500 text-ink-900' : 'bg-white/10 text-white/90'
                }`}
              >
                {t.content}
              </div>
            </div>
          ))}
          {sending && (
            <div className="flex justify-start">
              <div className="rounded-2xl bg-white/10 px-4 py-2.5 text-sm text-white/60">Thinking…</div>
            </div>
          )}
          <div ref={endRef} />
        </div>
        {error && <p className="mt-2 text-sm text-red-300">{error}</p>}
        <form onSubmit={handleSubmit} className="mt-3 flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask the agent…"
            className="flex-1 rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
          />
          <button
            type="submit"
            disabled={sending}
            className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-ink-900 disabled:opacity-60"
          >
            Send
          </button>
        </form>
      </GlassPanel>
    </div>
  )
}
