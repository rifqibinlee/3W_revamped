import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { GlassPanel } from '../components/GlassPanel'
import { api, ApiError, type AnnotationOut, type CommentOut, type ProjectOut, type TaskOut, type UserOut } from '../lib/api'
import { addCoverageHolesLayer, addStatusLayer, getSatelliteStyle } from '../lib/mapLayers'
import { useAuth } from '../lib/useAuth'

const DEFAULT_CENTER: [number, number] = [101.5, 3.1]

const COLUMNS: { status: string; label: string }[] = [
  { status: 'todo', label: 'To do' },
  { status: 'in_progress', label: 'In progress' },
  { status: 'pending_review', label: 'Pending review' },
  { status: 'done', label: 'Done' },
]

function elapsedSince(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(ms / 60000)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export function Projects() {
  const { user } = useAuth()
  const [projects, setProjects] = useState<ProjectOut[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [annotations, setAnnotations] = useState<AnnotationOut[]>([])
  const [tasks, setTasks] = useState<TaskOut[]>([])
  const [comments, setComments] = useState<CommentOut[]>([])
  const [users, setUsers] = useState<UserOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [assigneeId, setAssigneeId] = useState('')
  const [creating, setCreating] = useState(false)

  const [taskTitle, setTaskTitle] = useState('')
  const [taskAssigneeIds, setTaskAssigneeIds] = useState<string[]>([])
  const [assigneeMenuOpen, setAssigneeMenuOpen] = useState(false)
  const [taskDueDate, setTaskDueDate] = useState('')
  const [commentBody, setCommentBody] = useState('')

  const mapRef = useRef<maplibregl.Map | null>(null)

  function load() {
    Promise.all([api.listProjects(), api.listUsers()])
      .then(([rows, userRows]) => {
        const onlyProjects = rows.filter((p) => p.assignee_id)
        setProjects(onlyProjects)
        setUsers(userRows)
        if (onlyProjects.length > 0 && !selectedId) setSelectedId(onlyProjects[0].id)
      })
      .catch(() => setError('Could not load projects'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const selectedProject = projects.find((p) => p.id === selectedId) ?? null

  function refreshDetail() {
    if (!selectedId) return
    api.listAnnotations(selectedId).then(setAnnotations).catch(() => setAnnotations([]))
    api.listTasks(selectedId).then(setTasks).catch(() => setTasks([]))
    api.listProjectComments(selectedId).then(setComments).catch(() => setComments([]))
  }

  useEffect(refreshDetail, [selectedId])

  // A ref callback, not useRef + useEffect(..., []) — the page shows a
  // "Loading…" early return on first mount, so the map container div
  // doesn't exist in the DOM on the very first render. A plain
  // useEffect([]) only fires once, right after that first commit,
  // and finds a null ref forever after; a callback ref fires whenever
  // the node actually attaches, even if that's on a later render once
  // loading finishes.
  const mapContainerRef = useCallback((node: HTMLDivElement | null) => {
    if (mapRef.current) {
      mapRef.current.remove()
      mapRef.current = null
    }
    if (!node) return
    const map = new maplibregl.Map({ container: node, style: getSatelliteStyle(), center: DEFAULT_CENTER, zoom: 11 })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    map.on('load', () => {
      api.currentStatus().then((rows) => addStatusLayer(map, 'project-sites', rows)).catch(() => undefined)
      addCoverageHolesLayer(map).catch(() => undefined)
    })
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const apply = () => {
      const first = annotations[0]
      const center: [number, number] =
        first && first.geometry.type === 'Point' ? (first.geometry.coordinates as [number, number]) : DEFAULT_CENTER
      map.jumpTo({ center, zoom: first ? 14 : 11 })

      const sourceId = 'project-detail-annotations'
      const data: GeoJSON.FeatureCollection = {
        type: 'FeatureCollection',
        features: annotations.map((a) => ({
          type: 'Feature',
          geometry: a.geometry as unknown as GeoJSON.Geometry,
          properties: { label: a.label ?? '' },
        })),
      }
      const existing = map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined
      if (existing) {
        existing.setData(data)
        return
      }
      map.addSource(sourceId, { type: 'geojson', data })
      map.addLayer({ id: `${sourceId}-fill`, type: 'fill', source: sourceId, paint: { 'fill-color': '#facc15', 'fill-opacity': 0.15 } })
      map.addLayer({ id: `${sourceId}-line`, type: 'line', source: sourceId, paint: { 'line-color': '#facc15', 'line-width': 2 } })
      map.addLayer({
        id: `${sourceId}-point`,
        type: 'circle',
        source: sourceId,
        paint: { 'circle-radius': 7, 'circle-color': '#facc15', 'circle-stroke-width': 2, 'circle-stroke-color': '#1e1b4b' },
      })
    }
    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)
  }, [annotations])

  function userLabel(id: string): string {
    return users.find((u) => u.id === id)?.username ?? id.slice(0, 8)
  }

  async function handleCreateProject(e: FormEvent) {
    e.preventDefault()
    if (!assigneeId) return
    setCreating(true)
    try {
      const project = await api.createProject({ title, description: description || undefined, assignee_id: assigneeId })
      setTitle('')
      setDescription('')
      setAssigneeId('')
      load()
      setSelectedId(project.id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create project')
    } finally {
      setCreating(false)
    }
  }

  async function handleCreateTask(e: FormEvent) {
    e.preventDefault()
    if (!selectedId || taskAssigneeIds.length === 0) return
    try {
      await api.createTask(selectedId, {
        title: taskTitle,
        assignee_ids: taskAssigneeIds,
        due_date: new Date(taskDueDate).toISOString(),
      })
      setTaskTitle('')
      setTaskAssigneeIds([])
      setTaskDueDate('')
      setAssigneeMenuOpen(false)
      refreshDetail()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create task')
    }
  }

  async function handleAddComment(e: FormEvent) {
    e.preventDefault()
    if (!selectedId || !commentBody.trim()) return
    try {
      await api.addProjectComment(selectedId, commentBody.trim())
      setCommentBody('')
      refreshDetail()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not post comment')
    }
  }

  async function runTaskAction(action: () => Promise<TaskOut>) {
    try {
      await action()
      refreshDetail()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Action failed')
    }
  }

  function taskActions(task: TaskOut) {
    const isAssignee = task.assignee_ids.includes(user?.id ?? '')
    const isReviewer = task.creator_id === user?.id && !isAssignee
    if (task.status === 'todo' && isAssignee) {
      return (
        <button className="text-xs text-sky-300" onClick={() => runTaskAction(() => api.startTask(task.id))}>
          Start
        </button>
      )
    }
    if (task.status === 'in_progress' && isAssignee) {
      return (
        <button className="text-xs text-sky-300" onClick={() => runTaskAction(() => api.submitTask(task.id))}>
          Submit
        </button>
      )
    }
    if (task.status === 'pending_review' && isReviewer) {
      return (
        <div className="flex gap-2">
          <button className="text-xs text-green-300" onClick={() => runTaskAction(() => api.approveTask(task.id))}>
            Approve
          </button>
          <button
            className="text-xs text-red-300"
            onClick={() => {
              const reason = window.prompt('Reason for rejecting?')
              if (reason) runTaskAction(() => api.rejectTask(task.id, reason))
            }}
          >
            Reject
          </button>
        </div>
      )
    }
    return null
  }

  if (loading) return <p className="text-sm text-white/60">Loading…</p>

  const ganttStart = tasks.length > 0 ? Math.min(...tasks.map((t) => new Date(t.created_at).getTime())) : 0
  const ganttEnd = tasks.length > 0 ? Math.max(...tasks.map((t) => new Date(t.due_date).getTime())) : 0
  const ganttSpan = Math.max(ganttEnd - ganttStart, 1)

  return (
    <div className="grid gap-4 md:grid-cols-[280px_1fr]">
      <div className="space-y-4">
        <GlassPanel>
          <p className="mb-3.5 font-display text-sm font-semibold">New project</p>
          <form onSubmit={handleCreateProject} className="space-y-2.5">
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              placeholder="Title"
              className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
            />
            <select
              value={assigneeId}
              onChange={(e) => setAssigneeId(e.target.value)}
              required
              className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm focus:border-sky-400/60 focus:outline-none"
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
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Description"
              rows={2}
              className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
            />
            <button
              type="submit"
              disabled={creating}
              className="w-full rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-ink-900 disabled:opacity-60"
            >
              {creating ? 'Creating…' : 'Create project'}
            </button>
          </form>
          {error && <p className="mt-3 text-sm text-red-300">{error}</p>}
        </GlassPanel>

        <GlassPanel>
          <p className="mb-3.5 font-display text-sm font-semibold">Projects ({projects.length})</p>
          {projects.length === 0 ? (
            <p className="text-sm text-white/50">No projects yet.</p>
          ) : (
            <div className="divide-y divide-white/10">
              {projects.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setSelectedId(p.id)}
                  className={`w-full py-2.5 text-left text-sm ${selectedId === p.id ? 'text-white' : 'text-white/70'}`}
                >
                  {p.title}
                </button>
              ))}
            </div>
          )}
        </GlassPanel>
      </div>

      <div className="space-y-4">
        {!selectedProject && (
          <GlassPanel>
            <p className="text-sm text-white/50">Select or create a project.</p>
          </GlassPanel>
        )}

        {selectedProject && (
          <GlassPanel>
            <p className="font-display text-lg font-semibold">{selectedProject.title}</p>
            <p className="text-xs text-white/55">Assigned to {userLabel(selectedProject.assignee_id ?? '')}</p>
            <p className="mt-2 whitespace-pre-wrap text-sm text-white/75">
              {selectedProject.description || 'No description.'}
            </p>
          </GlassPanel>
        )}

        <div ref={mapContainerRef} className="h-[40vh] w-full overflow-hidden rounded-3xl border border-white/15" />

        {selectedProject && (
          <>
            <GlassPanel>
              <p className="mb-3.5 font-display text-sm font-semibold">New task</p>
              <form onSubmit={handleCreateTask} className="flex flex-wrap items-end gap-2">
                <input
                  type="text"
                  value={taskTitle}
                  onChange={(e) => setTaskTitle(e.target.value)}
                  required
                  placeholder="Task title"
                  className="min-w-[160px] flex-1 rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
                />
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setAssigneeMenuOpen((v) => !v)}
                    className="min-w-[140px] rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-left text-xs text-white/80 focus:border-sky-400/60 focus:outline-none"
                  >
                    {taskAssigneeIds.length === 0
                      ? 'Assignees…'
                      : taskAssigneeIds.map((id) => userLabel(id)).join(', ')}
                  </button>
                  {assigneeMenuOpen && (
                    <div className="absolute left-0 top-full z-20 mt-1 w-44 max-h-48 overflow-y-auto rounded-xl border border-white/15 bg-ink-900/95 p-1.5 text-xs backdrop-blur-xl">
                      {users.map((u) => (
                        <label key={u.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-white/5">
                          <input
                            type="checkbox"
                            checked={taskAssigneeIds.includes(u.id)}
                            onChange={(e) =>
                              setTaskAssigneeIds((prev) =>
                                e.target.checked ? [...prev, u.id] : prev.filter((id) => id !== u.id),
                              )
                            }
                            className="accent-sky-400"
                          />
                          {u.username}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
                <input
                  type="date"
                  value={taskDueDate}
                  onChange={(e) => setTaskDueDate(e.target.value)}
                  required
                  className="rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs focus:border-sky-400/60 focus:outline-none"
                />
                <button
                  type="submit"
                  className="rounded-lg bg-gradient-to-r from-accent-400 to-accent-500 px-3 py-1.5 text-xs font-semibold text-ink-900"
                >
                  Add task
                </button>
              </form>
            </GlassPanel>

            <GlassPanel>
              <p className="mb-3.5 font-display text-sm font-semibold">Tasks</p>
              <div className="grid gap-3 md:grid-cols-4">
                {COLUMNS.map((col) => (
                  <div key={col.status} className="rounded-2xl bg-white/5 p-2.5">
                    <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-white/50">{col.label}</p>
                    <div className="space-y-2">
                      {tasks
                        .filter((t) => t.status === col.status)
                        .map((t) => (
                          <div key={t.id} className="rounded-xl bg-white/8 p-2.5 text-xs">
                            <p className="font-medium text-white/90">{t.title}</p>
                            <p className="mt-1 text-white/55">
                              {t.assignee_ids.map(userLabel).join(', ')}
                            </p>
                            <p className="text-white/50">Due {new Date(t.due_date).toLocaleDateString()}</p>
                            <p className="text-white/40">Assigned {elapsedSince(t.created_at)}</p>
                            {t.rejection_reason && <p className="text-red-300">Rejected: {t.rejection_reason}</p>}
                            <div className="mt-1.5">{taskActions(t)}</div>
                          </div>
                        ))}
                    </div>
                  </div>
                ))}
              </div>
            </GlassPanel>

            <GlassPanel>
              <p className="mb-3.5 font-display text-sm font-semibold">Gantt</p>
              {tasks.length === 0 ? (
                <p className="text-sm text-white/50">No tasks yet.</p>
              ) : (
                <div className="space-y-2">
                  {tasks.map((t) => {
                    const start = new Date(t.created_at).getTime()
                    const end = new Date(t.due_date).getTime()
                    const leftPct = ((start - ganttStart) / ganttSpan) * 100
                    const widthPct = Math.max(((end - start) / ganttSpan) * 100, 2)
                    return (
                      <div key={t.id} className="flex items-center gap-2">
                        <span className="w-32 truncate text-xs text-white/70">{t.title}</span>
                        <div className="relative h-4 flex-1 rounded-full bg-white/5">
                          <div
                            className="absolute h-4 rounded-full bg-gradient-to-r from-sky-400 to-accent-400"
                            style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                          />
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </GlassPanel>

            <GlassPanel>
              <p className="mb-3.5 font-display text-sm font-semibold">Discussion</p>
              <div className="mb-3 max-h-60 space-y-2 overflow-y-auto">
                {comments.length === 0 ? (
                  <p className="text-sm text-white/50">No comments yet.</p>
                ) : (
                  comments.map((c) => (
                    <div key={c.id} className="rounded-xl bg-white/5 px-3 py-2 text-sm">
                      <p className="text-white/85">{c.body}</p>
                      <p className="text-[10px] text-white/40">
                        {userLabel(c.author_id)} · {new Date(c.created_at).toLocaleString()}
                      </p>
                    </div>
                  ))
                )}
              </div>
              <form onSubmit={handleAddComment} className="flex gap-2">
                <input
                  type="text"
                  value={commentBody}
                  onChange={(e) => setCommentBody(e.target.value)}
                  placeholder="Write a comment…"
                  className="flex-1 rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
                />
                <button
                  type="submit"
                  className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-ink-900"
                >
                  Send
                </button>
              </form>
            </GlassPanel>
          </>
        )}
      </div>
    </div>
  )
}
