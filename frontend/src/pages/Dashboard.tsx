import { useEffect, useMemo, useState } from 'react'
import { GlassPanel } from '../components/GlassPanel'
import { api, type AnnotationOut, type CurrentStatusRow } from '../lib/api'

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

export function Dashboard() {
  const [statusRows, setStatusRows] = useState<CurrentStatusRow[]>([])
  const [tasks, setTasks] = useState<AnnotationOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.currentStatus(), api.ganttRows()])
      .then(([status, gantt]) => {
        setStatusRows(status)
        setTasks(gantt)
      })
      .catch(() => setError('Could not load dashboard data'))
      .finally(() => setLoading(false))
  }, [])

  const congestedCount = useMemo(() => statusRows.filter((r) => r.congested).length, [statusRows])
  const congestionRate = statusRows.length ? ((congestedCount / statusRows.length) * 100).toFixed(1) : '0.0'

  const tasksByStatus = useMemo(() => {
    const counts: Record<string, number> = { todo: 0, in_progress: 0, pending_review: 0, done: 0 }
    for (const t of tasks) if (t.status) counts[t.status] = (counts[t.status] ?? 0) + 1
    return counts
  }, [tasks])

  if (loading) return <p className="text-sm text-white/60">Loading…</p>
  if (error) return <p className="text-sm text-red-300">{error}</p>

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <GlassPanel>
          <p className="mb-1.5 text-xs text-white/60">Network congestion</p>
          <div className="mb-3.5 flex items-baseline gap-2">
            <span className="font-display text-3xl font-semibold">{congestionRate}%</span>
            <span className="text-xs text-accent-400">of {statusRows.length} sectors</span>
          </div>
          <div className="grid grid-cols-3 gap-2.5">
            <StatTile value={tasksByStatus.in_progress} label="In progress" />
            <StatTile value={tasksByStatus.done} label="Completed" />
            <StatTile value={tasksByStatus.todo} label="Upcoming" />
          </div>
        </GlassPanel>

        <GlassPanel>
          <p className="mb-3.5 text-xs text-white/60">Congested sectors</p>
          <div className="flex items-baseline gap-2">
            <span className="font-display text-3xl font-semibold">{congestedCount}</span>
            <span className="text-xs text-white/50">currently flagged</span>
          </div>
        </GlassPanel>
      </div>

      <GlassPanel>
        <div className="mb-3.5 flex items-center justify-between">
          <p className="font-display text-sm font-semibold">My tasks</p>
          <span className="text-xs text-white/55">{tasks.length} total</span>
        </div>
        {tasks.length === 0 ? (
          <p className="text-sm text-white/50">No tasks assigned yet.</p>
        ) : (
          <div className="divide-y divide-white/10">
            {tasks.map((task) => (
              <div key={task.id} className="flex items-center gap-3 py-3">
                <div className="h-8 w-1 rounded-full bg-sky-500" />
                <div className="flex-1">
                  <p className="text-sm">{task.title}</p>
                  <p className="text-xs text-white/50">
                    {task.due_date ? `Due ${new Date(task.due_date).toLocaleDateString()}` : 'No due date'}
                  </p>
                </div>
                {task.status && (
                  <span className={`rounded-full px-2.5 py-1 text-xs ${STATUS_COLOR[task.status] ?? ''}`}>
                    {STATUS_LABEL[task.status] ?? task.status}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </GlassPanel>
    </div>
  )
}

function StatTile({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded-2xl bg-white/6 px-3 py-2.5">
      <p className="font-display text-lg font-semibold">{value}</p>
      <p className="text-[11px] text-white/55">{label}</p>
    </div>
  )
}
