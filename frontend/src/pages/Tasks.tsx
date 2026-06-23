import { useEffect, useState, type FormEvent } from 'react'
import { GlassPanel } from '../components/GlassPanel'
import { api, ApiError, type ProjectOut, type TaskOut, type UserOut } from '../lib/api'
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
  const [projects, setProjects] = useState<ProjectOut[]>([])
  const [tasks, setTasks] = useState<TaskOut[]>([])
  const [users, setUsers] = useState<UserOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)

  const [title, setTitle] = useState('')
  const [assigneeId, setAssigneeId] = useState('')
  const [creating, setCreating] = useState(false)

  function load() {
    Promise.all([api.listProjects(), api.ganttRows(), api.listUsers()])
      .then(([projectRows, taskRows, userRows]) => {
        setProjects(projectRows)
        setTasks(taskRows)
        setUsers(userRows)
      })
      .catch(() => setError('Could not load projects'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  function userLabel(id: string | null): string {
    if (!id) return '—'
    return users.find((u) => u.id === id)?.username ?? id.slice(0, 8)
  }

  async function handleCreateProject(e: FormEvent) {
    e.preventDefault()
    setCreating(true)
    try {
      await api.createProject({ title, assignee_id: assigneeId || undefined })
      setTitle('')
      setAssigneeId('')
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create project')
    } finally {
      setCreating(false)
    }
  }

  async function runAction(action: () => Promise<TaskOut>) {
    try {
      await action()
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Action failed')
    }
  }

  if (loading) return <p className="text-sm text-white/60">Loading…</p>

  const selectedProject = projects.find((p) => p.id === selectedProjectId) ?? null
  const tasksForSelected = tasks.filter((t) => t.project_id === selectedProjectId)

  return (
    <div className="space-y-4">
      <GlassPanel>
        <p className="mb-3.5 font-display text-sm font-semibold">New note or project</p>
        <form onSubmit={handleCreateProject} className="flex flex-wrap items-end gap-3">
          <div className="min-w-[200px] flex-1">
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
              Title
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              placeholder="e.g. Antenna survey at SITE004"
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

      <div className="grid gap-4 md:grid-cols-[1fr_1.4fr]">
        <GlassPanel>
          <p className="mb-3.5 font-display text-sm font-semibold">Notes &amp; projects ({projects.length})</p>
          {projects.length === 0 ? (
            <p className="text-sm text-white/50">Nothing yet — create one above.</p>
          ) : (
            <div className="divide-y divide-white/10">
              {projects.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setSelectedProjectId(p.id)}
                  className={`w-full py-2.5 text-left ${selectedProjectId === p.id ? 'text-white' : 'text-white/75'}`}
                >
                  <p className="text-sm">{p.title}</p>
                  <p className="text-xs text-white/50">
                    {p.assignee_id ? `Project · ${userLabel(p.assignee_id)}` : 'Note'}
                  </p>
                </button>
              ))}
            </div>
          )}
        </GlassPanel>

        <GlassPanel>
          {!selectedProject && <p className="text-sm text-white/50">Select a note or project to view its tasks.</p>}

          {selectedProject && (
            <>
              <p className="mb-1 font-display text-sm font-semibold">{selectedProject.title}</p>
              <p className="mb-3.5 text-xs text-white/55">
                {selectedProject.assignee_id
                  ? `Project, assigned to ${userLabel(selectedProject.assignee_id)}`
                  : 'Note (unassigned) — assign it to someone to create tasks under it'}
              </p>

              {!selectedProject.assignee_id && (
                <p className="text-sm text-white/50">No tasks possible until this becomes a project.</p>
              )}

              {selectedProject.assignee_id && (
                <>
                  <NewTaskForm projectId={selectedProject.id} users={users} onCreated={load} />

                  {tasksForSelected.length === 0 && (
                    <p className="mt-3 text-sm text-white/50">No tasks yet under this project.</p>
                  )}

                  {tasksForSelected.length > 0 && (
                    <div className="mt-3 divide-y divide-white/10">
                      {tasksForSelected.map((task) => (
                        <div key={task.id} className="flex flex-wrap items-center gap-3 py-3">
                          <div className="flex-1">
                            <p className="text-sm">{task.title}</p>
                            <p className="text-xs text-white/50">
                              Assignee: {userLabel(task.assignee_id)} · Due{' '}
                              {new Date(task.due_date).toLocaleDateString()}
                            </p>
                            {task.rejection_reason && (
                              <p className="text-xs text-red-300">Rejected: {task.rejection_reason}</p>
                            )}
                          </div>
                          <span className={`rounded-full px-2.5 py-1 text-xs ${STATUS_COLOR[task.status] ?? ''}`}>
                            {STATUS_LABEL[task.status] ?? task.status}
                          </span>
                          <TaskActions task={task} currentUserId={user?.id} onAction={runAction} />
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </GlassPanel>
      </div>
    </div>
  )
}

function NewTaskForm({
  projectId,
  users,
  onCreated,
}: {
  projectId: string
  users: UserOut[]
  onCreated: () => void
}) {
  const [title, setTitle] = useState('')
  const [assigneeId, setAssigneeId] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      await api.createTask(projectId, { title, assignee_id: assigneeId, due_date: new Date(dueDate).toISOString() })
      setTitle('')
      setAssigneeId('')
      setDueDate('')
      onCreated()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create task')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-2 rounded-xl bg-white/5 p-3">
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        required
        placeholder="New task title"
        className="min-w-[160px] flex-1 rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
      />
      <select
        value={assigneeId}
        onChange={(e) => setAssigneeId(e.target.value)}
        required
        className="rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs focus:border-sky-400/60 focus:outline-none"
      >
        <option value="" className="bg-ink-900">
          Assignee…
        </option>
        {users.map((u) => (
          <option key={u.id} value={u.id} className="bg-ink-900">
            {u.username}
          </option>
        ))}
      </select>
      <input
        type="date"
        value={dueDate}
        onChange={(e) => setDueDate(e.target.value)}
        required
        className="rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs focus:border-sky-400/60 focus:outline-none"
      />
      <button
        type="submit"
        disabled={submitting}
        className="rounded-lg bg-gradient-to-r from-accent-400 to-accent-500 px-3 py-1.5 text-xs font-semibold text-ink-900 disabled:opacity-60"
      >
        Add task
      </button>
      {error && <p className="w-full text-xs text-red-300">{error}</p>}
    </form>
  )
}

function TaskActions({
  task,
  currentUserId,
  onAction,
}: {
  task: TaskOut
  currentUserId: string | undefined
  onAction: (action: () => Promise<TaskOut>) => void
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
