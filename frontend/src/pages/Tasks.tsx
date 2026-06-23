import { useEffect, useState, type FormEvent } from 'react'
import { GlassPanel } from '../components/GlassPanel'
import { api, ApiError, type AnnotationOut, type UserOut } from '../lib/api'
import { useAuth } from '../lib/useAuth'

const STATUS_LABEL: Record<string, string> = {
  todo: 'Todo',
  in_progress: 'In progress',
  pending_review: 'Pending review',
  done: 'Done',
  rejected: 'Rejected',
}

const STATUS_COLOR: Record<string, string> = {
  todo: 'bg-white/12 text-white/70',
  in_progress: 'bg-sky-500/20 text-sky-300',
  pending_review: 'bg-accent-400/20 text-accent-400',
  done: 'bg-green-500/20 text-green-300',
  rejected: 'bg-red-500/20 text-red-300',
}

export function Tasks() {
  const { user } = useAuth()
  const [tasks, setTasks] = useState<AnnotationOut[]>([])
  const [users, setUsers] = useState<UserOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [title, setTitle] = useState('')
  const [assigneeId, setAssigneeId] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [creating, setCreating] = useState(false)

  function load() {
    Promise.all([api.ganttRows(), api.listUsers()])
      .then(([taskRows, userRows]) => {
        setTasks(taskRows)
        setUsers(userRows)
      })
      .catch(() => setError('Could not load tasks'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  function userLabel(id: string | null): string {
    if (!id) return '—'
    return users.find((u) => u.id === id)?.username ?? id.slice(0, 8)
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setCreating(true)
    try {
      await api.createAnnotation({
        title,
        geometry: { type: 'Point', coordinates: [0, 0] },
        assignee_id: assigneeId || undefined,
        due_date: assigneeId && dueDate ? new Date(dueDate).toISOString() : undefined,
      })
      setTitle('')
      setAssigneeId('')
      setDueDate('')
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create task')
    } finally {
      setCreating(false)
    }
  }

  async function runAction(action: () => Promise<AnnotationOut>) {
    try {
      await action()
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Action failed')
    }
  }

  if (loading) return <p className="text-sm text-white/60">Loading…</p>

  return (
    <div className="space-y-4">
      <GlassPanel>
        <p className="mb-3.5 font-display text-sm font-semibold">New note or task</p>
        <form onSubmit={handleCreate} className="flex flex-wrap items-end gap-3">
          <div className="min-w-[200px] flex-1">
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
              Title
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              placeholder="e.g. Replace radio at SITE004"
              className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
            />
          </div>
          <div className="min-w-[160px]">
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
              Assignee (optional)
            </label>
            <select
              value={assigneeId}
              onChange={(e) => setAssigneeId(e.target.value)}
              className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm focus:border-sky-400/60 focus:outline-none"
            >
              <option value="" className="bg-ink-900">
                Note (unassigned)
              </option>
              {users.map((u) => (
                <option key={u.id} value={u.id} className="bg-ink-900">
                  {u.username}
                </option>
              ))}
            </select>
          </div>
          {assigneeId && (
            <div className="min-w-[150px]">
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
                Due date
              </label>
              <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                required
                className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm focus:border-sky-400/60 focus:outline-none"
              />
            </div>
          )}
          <button
            type="submit"
            disabled={creating}
            className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-5 py-2 font-display text-sm font-semibold text-ink-900 disabled:opacity-60"
          >
            {creating ? 'Creating…' : 'Create'}
          </button>
        </form>
        {error && <p className="mt-3 text-sm text-red-300">{error}</p>}
      </GlassPanel>

      <GlassPanel>
        <p className="mb-3.5 font-display text-sm font-semibold">Tasks ({tasks.length})</p>
        {tasks.length === 0 ? (
          <p className="text-sm text-white/50">No tasks yet — assign a note to someone to create one.</p>
        ) : (
          <div className="divide-y divide-white/10">
            {tasks.map((task) => (
              <div key={task.id} className="flex flex-wrap items-center gap-3 py-3">
                <div className="flex-1">
                  <p className="text-sm">{task.title}</p>
                  <p className="text-xs text-white/50">
                    Assignee: {userLabel(task.assignee_id)} ·{' '}
                    {task.due_date ? `Due ${new Date(task.due_date).toLocaleDateString()}` : 'No due date'}
                  </p>
                  {task.rejection_reason && (
                    <p className="text-xs text-red-300">Rejected: {task.rejection_reason}</p>
                  )}
                </div>
                {task.status && (
                  <span className={`rounded-full px-2.5 py-1 text-xs ${STATUS_COLOR[task.status] ?? ''}`}>
                    {STATUS_LABEL[task.status] ?? task.status}
                  </span>
                )}
                <TaskActions task={task} currentUserId={user?.id} onAction={runAction} />
              </div>
            ))}
          </div>
        )}
      </GlassPanel>
    </div>
  )
}

function TaskActions({
  task,
  currentUserId,
  onAction,
}: {
  task: AnnotationOut
  currentUserId: string | undefined
  onAction: (action: () => Promise<AnnotationOut>) => void
}) {
  const isAssignee = task.assignee_id === currentUserId
  const isReviewer = task.creator_id === currentUserId && task.assignee_id !== currentUserId

  const btnClass = 'rounded-full border border-white/20 px-3 py-1 text-xs text-white/80 hover:bg-white/10'

  if (task.status === 'todo' && isAssignee) {
    return (
      <button className={btnClass} onClick={() => onAction(() => api.startTask(task.id))}>
        Start
      </button>
    )
  }
  if (task.status === 'in_progress' && isAssignee) {
    return (
      <button className={btnClass} onClick={() => onAction(() => api.submitTask(task.id))}>
        Submit for review
      </button>
    )
  }
  if (task.status === 'pending_review' && isReviewer) {
    return (
      <div className="flex gap-2">
        <button className={btnClass} onClick={() => onAction(() => api.approveTask(task.id))}>
          Approve
        </button>
        <button
          className={btnClass}
          onClick={() => {
            const reason = window.prompt('Reason for rejecting?')
            if (reason) onAction(() => api.rejectTask(task.id, reason))
          }}
        >
          Reject
        </button>
      </div>
    )
  }
  return null
}
