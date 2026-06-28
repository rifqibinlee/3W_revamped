import { useEffect, useRef, useState, type FormEvent } from 'react'
import { GlassPanel } from '../components/GlassPanel'
import { api, ApiError, type ConversationOut, type MessageOut, type UserOut } from '../lib/api'
import { useAuth } from '../lib/useAuth'

// A small curated set rather than a full emoji-mart-style library —
// enough common reactions/expressions for a work chat without a new
// dependency.
const EMOJIS = [
  '😀', '😂', '😅', '😉', '😊', '😍', '🤔', '😎', '😴', '😢',
  '😡', '👍', '👎', '🙏', '👏', '🎉', '🔥', '✅', '❌', '⚠️',
  '📍', '📡', '🔧', '🚀', '💡', '☕', '👀', '💯', '🙌', '😬',
]

export function Chat() {
  const { user } = useAuth()
  const [conversations, setConversations] = useState<ConversationOut[]>([])
  const [users, setUsers] = useState<UserOut[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [messages, setMessages] = useState<MessageOut[]>([])
  const [body, setBody] = useState('')
  const [error, setError] = useState<string | null>(null)

  const [recipientQuery, setRecipientQuery] = useState('')
  const [recipientSuggestionsOpen, setRecipientSuggestionsOpen] = useState(false)
  const [selectedRecipients, setSelectedRecipients] = useState<UserOut[]>([])
  const [groupTitle, setGroupTitle] = useState('')
  const [emojiPickerOpen, setEmojiPickerOpen] = useState(false)

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

  const recipientMatches =
    recipientQuery.trim().length === 0
      ? []
      : users.filter(
          (u) =>
            u.id !== user?.id &&
            !selectedRecipients.some((r) => r.id === u.id) &&
            u.username.toLowerCase().includes(recipientQuery.trim().toLowerCase()),
        )

  function addRecipient(u: UserOut) {
    setSelectedRecipients((prev) => [...prev, u])
    setRecipientQuery('')
    setRecipientSuggestionsOpen(false)
  }

  function removeRecipient(id: string) {
    setSelectedRecipients((prev) => prev.filter((u) => u.id !== id))
  }

  async function handleStartConversation(e: FormEvent) {
    e.preventDefault()
    if (selectedRecipients.length === 0) return
    try {
      const conv =
        selectedRecipients.length === 1
          ? await api.createDirectConversation(selectedRecipients[0].id)
          : await api.createGroupConversation(
              groupTitle.trim() || selectedRecipients.map((u) => u.username).join(', '),
              selectedRecipients.map((u) => u.id),
            )
      setSelectedRecipients([])
      setGroupTitle('')
      setRecipientQuery('')
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
        <form onSubmit={handleStartConversation} className="mb-3 space-y-1.5">
          {selectedRecipients.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {selectedRecipients.map((u) => (
                <span key={u.id} className="flex items-center gap-1 rounded-full bg-sky-400/15 px-2 py-0.5 text-[11px] text-sky-200">
                  {u.username}
                  <button type="button" onClick={() => removeRecipient(u.id)} className="text-sky-200/60 hover:text-white">
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          {selectedRecipients.length > 1 && (
            <input
              type="text"
              value={groupTitle}
              onChange={(e) => setGroupTitle(e.target.value)}
              placeholder="Group name (optional)"
              className="w-full rounded-lg border border-white/15 bg-white/5 px-2 py-1.5 text-xs placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
            />
          )}
          <div className="relative flex gap-1.5">
            <input
              type="text"
              value={recipientQuery}
              onChange={(e) => {
                setRecipientQuery(e.target.value)
                setRecipientSuggestionsOpen(true)
              }}
              onFocus={() => setRecipientSuggestionsOpen(true)}
              onBlur={() => setTimeout(() => setRecipientSuggestionsOpen(false), 150)}
              placeholder={selectedRecipients.length === 0 ? 'New chat with…' : 'Add another person…'}
              className="min-w-0 flex-1 rounded-lg border border-white/15 bg-white/5 px-2 py-1.5 text-xs placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
            />
            <button
              type="submit"
              disabled={selectedRecipients.length === 0}
              className="rounded-lg bg-gradient-to-r from-accent-400 to-accent-500 px-3 py-1.5 text-xs font-semibold text-ink-900 disabled:opacity-40"
            >
              Go
            </button>
            {recipientSuggestionsOpen && recipientMatches.length > 0 && (
              <div className="absolute left-0 top-full z-10 mt-1 w-full overflow-hidden rounded-lg border border-white/15 bg-ink-900/95 text-xs backdrop-blur-xl">
                {recipientMatches.slice(0, 6).map((u) => (
                  <button
                    key={u.id}
                    type="button"
                    onClick={() => addRecipient(u)}
                    className="block w-full px-2.5 py-1.5 text-left text-white/80 hover:bg-white/10"
                  >
                    {u.username}
                  </button>
                ))}
              </div>
            )}
          </div>
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
            <form onSubmit={handleSend} className="relative mt-3 flex gap-2">
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setEmojiPickerOpen((v) => !v)}
                  title="Add emoji"
                  className="flex h-full items-center justify-center rounded-xl border border-white/15 px-2.5 text-base text-white/70 hover:bg-white/5"
                >
                  🙂
                </button>
                {emojiPickerOpen && (
                  <div className="absolute bottom-full left-0 z-10 mb-2 grid w-56 grid-cols-6 gap-1 rounded-2xl border border-white/15 bg-ink-900/95 p-2 backdrop-blur-xl">
                    {EMOJIS.map((emoji) => (
                      <button
                        key={emoji}
                        type="button"
                        onClick={() => {
                          setBody((prev) => prev + emoji)
                          setEmojiPickerOpen(false)
                        }}
                        className="rounded-lg p-1 text-lg hover:bg-white/10"
                      >
                        {emoji}
                      </button>
                    ))}
                  </div>
                )}
              </div>
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
