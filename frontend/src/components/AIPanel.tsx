import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useAIPanel } from '../lib/useAIPanel'
import { GlassPanel } from './GlassPanel'

// Persistent across every page (mounted once in AppShell, state lives
// in AIPanelProvider above the per-route AppShell instances) — a
// collapsible side panel with a floating tab, not a dedicated nav
// route, matching the pattern from the BEKAL app's "Sybil" assistant.
export function AIPanel() {
  const { open, setOpen, turns, sending, error, sendMessage } = useAIPanel()
  const [input, setInput] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns, open])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const message = input.trim()
    if (!message) return
    setInput('')
    await sendMessage(message)
  }

  return (
    <>
      <button
        onClick={() => setOpen(!open)}
        title="Graham, the network ops assistant"
        style={{ writingMode: 'vertical-rl' }}
        className={`fixed right-0 top-1/2 z-40 flex -translate-y-1/2 items-center gap-2 rounded-l-xl border border-r-0 border-white/20 px-2 py-3 text-xs font-semibold backdrop-blur-xl transition-colors ${
          open ? 'bg-accent-400 text-ink-900' : 'bg-ink-900/85 text-white/70 hover:text-white'
        }`}
      >
        Graham
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex justify-end lg:inset-auto lg:bottom-4 lg:right-16 lg:top-20">
          <div className="absolute inset-0 bg-ink-950/60 backdrop-blur-sm lg:hidden" onClick={() => setOpen(false)} />
          <GlassPanel className="relative z-10 flex h-full w-full max-w-sm flex-col overflow-hidden lg:h-auto lg:w-80">
            <div className="mb-3 flex items-center justify-between">
              <p className="font-display text-sm font-semibold">Graham</p>
              <button onClick={() => setOpen(false)} className="text-white/50 hover:text-white">
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M6 6l12 12M18 6 6 18" />
                </svg>
              </button>
            </div>
            <div className="flex-1 space-y-3 overflow-y-auto pr-1">
              {turns.length === 0 && (
                <p className="text-sm text-white/50">
                  Ask about congestion, CAPEX upgrades, or network KPIs — e.g. "Which sites in Central are congested?"
                </p>
              )}
              {turns.map((t, i) => (
                <div key={i} className={`flex ${t.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap ${
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
                placeholder="Ask Graham…"
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
      )}
    </>
  )
}
