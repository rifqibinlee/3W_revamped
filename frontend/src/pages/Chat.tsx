import { useEffect, useRef, useState, type FormEvent } from 'react'
import { GlassPanel } from '../components/GlassPanel'
import { api, ApiError, type ConversationOut, type MessageOut, type UserOut } from '../lib/api'
import { useAuth } from '../lib/useAuth'

export function Chat() {
  const { user } = useAuth()
  const [conversations, setConversations] = useState<ConversationOut[]>([])
  const [users, setUsers] = useState<UserOut[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [messages, setMessages] = useState<MessageOut[]>([])
  const [body, setBody] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [newRecipientId, setNewRecipientId] = useState('')

  const messagesEndRef = useRef<HTMLDivElement>(null)

  function loadConversations() {
    api.listConversations().then(setConversations).catch(() => setError('Could not load conversations'))
  }

  useEffect(() => {
    loadConversations()
    api.listUsers().then(setUsers).catch(() => undefined)
  }, [])

  function loadMessages(conversationId: string) {
    api.listMessages(conversationId).then(setMessages).catch(() => setMessages([]))
  }

  useEffect(() => {
    if (!selectedId) return
    loadMessages(selectedId)
    const interval = setInterval(() => loadMessages(selectedId), 4000)
    return () => clearInterval(interval)
  }, [selectedId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  function userLabel(id: string): string {
    if (id === user?.id) return 'You'
    return users.find((u) => u.id === id)?.username ?? id.slice(0, 8)
  }

  function conversationLabel(c: ConversationOut): string {
    if (c.is_group) return c.title ?? 'Group chat'
    const otherId = c.participant_ids.find((id) => id !== user?.id)
    return otherId ? userLabel(otherId) : 'Conversation'
  }

  async function handleStartConversation(e: FormEvent) {
    e.preventDefault()
    if (!newRecipientId) return
    try {
      const conv = await api.createDirectConversation(newRecipientId)
      setNewRecipientId('')
      loadConversations()
      setSelectedId(conv.id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start conversation')
    }
  }

  async function handleSend(e: FormEvent) {
    e.preventDefault()
    if (!selectedId || !body.trim()) return
    try {
      await api.sendMessage(selectedId, body.trim())
      setBody('')
      loadMessages(selectedId)
      loadConversations()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not send message')
    }
  }

  async function handleDeleteMessage(messageId: string) {
    if (!selectedId || !window.confirm('Delete this message?')) return
    try {
      await api.deleteMessage(messageId)
      loadMessages(selectedId)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not delete message')
    }
  }

  return (
    <div className="grid h-[75vh] gap-4 md:grid-cols-[260px_1fr]">
      <GlassPanel className="flex flex-col overflow-hidden">
        <p className="mb-3 font-display text-sm font-semibold">Conversations</p>
        <form onSubmit={handleStartConversation} className="mb-3 flex gap-1.5">
          <select
            value={newRecipientId}
            onChange={(e) => setNewRecipientId(e.target.value)}
            className="min-w-0 flex-1 rounded-lg border border-white/15 bg-white/5 px-2 py-1.5 text-xs focus:border-sky-400/60 focus:outline-none"
          >
            <option value="" className="bg-ink-900">
              New chat with…
            </option>
            {users.filter((u) => u.id !== user?.id).map((u) => (
              <option key={u.id} value={u.id} className="bg-ink-900">
                {u.username}
              </option>
            ))}
          </select>
          <button type="submit" className="rounded-lg bg-gradient-to-r from-accent-400 to-accent-500 px-3 py-1.5 text-xs font-semibold text-ink-900">
            Go
          </button>
        </form>

        <div className="flex-1 space-y-1 overflow-y-auto">
          {conversations.length === 0 ? (
            <p className="text-sm text-white/50">No conversations yet.</p>
          ) : (
            conversations.map((c) => (
              <button
                key={c.id}
                onClick={() => setSelectedId(c.id)}
                className={`w-full rounded-xl px-3 py-2 text-left text-sm ${
                  selectedId === c.id ? 'bg-white/10 text-white' : 'text-white/70 hover:bg-white/5'
                }`}
              >
                {conversationLabel(c)}
              </button>
            ))
          )}
        </div>
      </GlassPanel>

      <GlassPanel className="flex flex-col overflow-hidden">
        {!selectedId ? (
          <p className="text-sm text-white/50">Select or start a conversation.</p>
        ) : (
          <>
            <div className="flex-1 space-y-2 overflow-y-auto pr-1">
              {messages.map((m) => {
                const mine = m.sender_id === user?.id
                return (
                  <div key={m.id} className={`group flex items-center gap-1.5 ${mine ? 'justify-end' : 'justify-start'}`}>
                    {user?.role === 'super_admin' && (
                      <button
                        onClick={() => handleDeleteMessage(m.id)}
                        title="Delete message"
                        className="hidden text-white/30 hover:text-red-300 group-hover:block"
                      >
                        <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3" />
                        </svg>
                      </button>
                    )}
                    <div
                      className={`max-w-xs rounded-2xl px-3.5 py-2 text-sm ${
                        mine ? 'bg-gradient-to-r from-sky-400 to-sky-500 text-ink-900' : 'bg-white/10 text-white/90'
                      }`}
                    >
                      {!mine && <p className="mb-0.5 text-[10px] font-semibold text-white/50">{userLabel(m.sender_id)}</p>}
                      <p>{m.body}</p>
                      <p className="mt-1 text-[10px] opacity-60">{new Date(m.created_at).toLocaleTimeString()}</p>
                    </div>
                  </div>
                )
              })}
              <div ref={messagesEndRef} />
            </div>
            <form onSubmit={handleSend} className="mt-3 flex gap-2">
              <input
                type="text"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Type a message…"
                className="flex-1 rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
              />
              <button type="submit" className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-ink-900">
                Send
              </button>
            </form>
          </>
        )}
        {error && <p className="mt-2 text-sm text-red-300">{error}</p>}
      </GlassPanel>
    </div>
  )
}
