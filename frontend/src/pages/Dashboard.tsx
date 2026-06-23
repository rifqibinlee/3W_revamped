import { useCallback, useEffect, useMemo, useState } from 'react'
import { DataTable, type Column } from '../components/DataTable'
import { FilterBar } from '../components/FilterBar'
import { GlassPanel } from '../components/GlassPanel'
import {
  api,
  type AnalyticsFilters,
  type FilterOptions,
  type ForecastRow,
  type SectorMetricRow,
  type SummaryStats,
  type TaskOut,
} from '../lib/api'

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

const EMPTY_OPTIONS: FilterOptions = { regions: [], years: [], weeks: [], operators: [] }

function CongestedBadge({ congested }: { congested: boolean }) {
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-xs ${
        congested ? 'bg-red-500/20 text-red-300' : 'bg-green-500/20 text-green-300'
      }`}
    >
      {congested ? 'Congested' : 'Normal'}
    </span>
  )
}

const sectorColumns: Column<SectorMetricRow>[] = [
  { key: 'zoom_sector_id', label: 'Sector' },
  { key: 'region', label: 'Region' },
  { key: 'operator', label: 'Operator' },
  { key: 'eric_prb_util_rate', label: 'PRB %', render: (r) => r.eric_prb_util_rate?.toFixed(1) },
  { key: 'eric_dl_user_ip_thpt', label: 'Thpt (Mbps)', render: (r) => r.eric_dl_user_ip_thpt?.toFixed(1) },
  { key: 'eric_data_volume_ul_dl', label: 'Volume (GB)', render: (r) => r.eric_data_volume_ul_dl?.toFixed(1) },
  { key: 'congested', label: 'Status', render: (r) => <CongestedBadge congested={r.congested} /> },
]

const congestedColumns: Column<SectorMetricRow>[] = [
  { key: 'zoom_sector_id', label: 'Sector' },
  { key: 'region', label: 'Region' },
  { key: 'eric_prb_util_rate', label: 'PRB %', render: (r) => r.eric_prb_util_rate?.toFixed(1) },
  { key: 'eric_dl_user_ip_thpt', label: 'Thpt (Mbps)', render: (r) => r.eric_dl_user_ip_thpt?.toFixed(1) },
  { key: 'congested_weeks', label: 'Weeks congested' },
]

const forecastColumns: Column<ForecastRow>[] = [
  { key: 'zoom_sector_id', label: 'Sector' },
  { key: 'year', label: 'Year' },
  { key: 'week', label: 'Week' },
  {
    key: 'predicted_eric_prb_util_rate',
    label: 'Predicted PRB %',
    render: (r) => r.predicted_eric_prb_util_rate?.toFixed(1),
  },
  {
    key: 'predicted_eric_dl_user_ip_thpt',
    label: 'Predicted thpt',
    render: (r) => r.predicted_eric_dl_user_ip_thpt?.toFixed(1),
  },
  { key: 'congested', label: 'Forecast status', render: (r) => <CongestedBadge congested={r.congested} /> },
]

export function Dashboard() {
  const [tasks, setTasks] = useState<TaskOut[]>([])
  const [options, setOptions] = useState<FilterOptions>(EMPTY_OPTIONS)
  const [filters, setFilters] = useState<AnalyticsFilters>({})
  const [summary, setSummary] = useState<SummaryStats>({ total_sectors: 0, congested_count: 0, avg_volume_gb: 0 })
  const [sectorRows, setSectorRows] = useState<SectorMetricRow[]>([])
  const [congestedRows, setCongestedRows] = useState<SectorMetricRow[]>([])
  const [forecastRows, setForecastRows] = useState<ForecastRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.ganttRows(), api.filterOptions()])
      .then(([gantt, filterOptions]) => {
        setTasks(gantt)
        setOptions(filterOptions)
      })
      .catch(() => setError('Could not load dashboard data'))
      .finally(() => setLoading(false))
  }, [])

  const refresh = useCallback((currentFilters: AnalyticsFilters) => {
    Promise.all([
      api.summary(currentFilters),
      api.sectorMetrics(currentFilters),
      api.congestedSectors(currentFilters),
      api.forecastTable(currentFilters),
    ])
      .then(([summaryStats, sectors, congested, forecast]) => {
        setSummary(summaryStats)
        setSectorRows(sectors)
        setCongestedRows(congested)
        setForecastRows(forecast)
      })
      .catch(() => setError('Could not load analytics data'))
  }, [])

  useEffect(() => {
    refresh(filters)
  }, [filters, refresh])

  const tasksByStatus = useMemo(() => {
    const counts: Record<string, number> = { todo: 0, in_progress: 0, pending_review: 0, done: 0 }
    for (const t of tasks) if (t.status) counts[t.status] = (counts[t.status] ?? 0) + 1
    return counts
  }, [tasks])

  if (loading) return <p className="text-sm text-white/60">Loading…</p>
  if (error) return <p className="text-sm text-red-300">{error}</p>

  return (
    <div className="space-y-4">
      <GlassPanel>
        <FilterBar options={options} filters={filters} onChange={setFilters} />
        <div className="mt-4 flex flex-wrap gap-3 border-t border-white/10 pt-4">
          <StatTile value={summary.total_sectors} label="Total sectors" />
          <StatTile value={summary.congested_count} label="Congested sectors" tone="danger" />
          <StatTile value={summary.avg_volume_gb} label="Avg vol (GB)" tone="success" />
        </div>
      </GlassPanel>

      <div className="grid gap-4 md:grid-cols-2">
        <GlassPanel>
          <p className="mb-1.5 text-xs text-white/60">Network congestion</p>
          <div className="mb-3.5 flex items-baseline gap-2">
            <span className="font-display text-3xl font-semibold">
              {summary.total_sectors ? ((summary.congested_count / summary.total_sectors) * 100).toFixed(1) : '0.0'}%
            </span>
            <span className="text-xs text-accent-400">of {summary.total_sectors} sectors</span>
          </div>
          <div className="grid grid-cols-3 gap-2.5">
            <StatTile value={tasksByStatus.in_progress} label="In progress" />
            <StatTile value={tasksByStatus.done} label="Completed" />
            <StatTile value={tasksByStatus.todo} label="Upcoming" />
          </div>
        </GlassPanel>

        <GlassPanel>
          <div className="mb-3.5 flex items-center justify-between">
            <p className="font-display text-sm font-semibold">My tasks</p>
            <span className="text-xs text-white/55">{tasks.length} total</span>
          </div>
          {tasks.length === 0 ? (
            <p className="text-sm text-white/50">No tasks assigned yet.</p>
          ) : (
            <div className="divide-y divide-white/10">
              {tasks.slice(0, 3).map((task) => (
                <div key={task.id} className="flex items-center gap-3 py-2.5">
                  <div className="h-7 w-1 rounded-full bg-sky-500" />
                  <p className="flex-1 text-sm">{task.title}</p>
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

      <GlassPanel>
        <p className="mb-1 font-display text-sm font-semibold">Sector performance metrics</p>
        <p className="mb-3.5 text-xs text-white/55">Weekly aggregated performance indicators across all sectors.</p>
        <DataTable columns={sectorColumns} rows={sectorRows} emptyMessage="No sector data — run the ETL pipeline first." />
      </GlassPanel>

      <GlassPanel>
        <div className="flex flex-wrap items-center gap-4 text-xs text-white/60">
          <span className="font-medium text-white/80">Legend</span>
          <LegendItem color="bg-white/70" label="Actual" />
          <LegendItem color="border border-dashed border-green-400" label="Forecast (vol)" />
          <LegendItem color="border border-dashed border-accent-400" label="Forecast (PRB)" />
          <LegendItem color="border border-dashed border-sky-400" label="Forecast (thpt)" />
          <LegendItem color="bg-red-500/30 border border-red-400" label="Congested/alert" />
        </div>
      </GlassPanel>

      <GlassPanel>
        <p className="mb-1 font-display text-sm font-semibold">Future performance forecasts</p>
        <p className="mb-3.5 text-xs text-white/55">52-week predictions per sector.</p>
        <DataTable columns={forecastColumns} rows={forecastRows} emptyMessage="No forecast data — run forecast_results first." />
      </GlassPanel>

      <GlassPanel>
        <p className="mb-1 font-display text-sm font-semibold">Congested sectors</p>
        <p className="mb-3 text-xs text-white/55">Sectors experiencing performance degradation.</p>
        <div className="mb-4 rounded-xl border border-red-400/30 bg-red-500/10 p-3 text-xs text-red-200">
          <strong>Congestion criteria</strong> (urban/KMC + NIC: PRB ≥80% &amp; thpt &lt;7 Mbps · urban/KMC: PRB
          ≥80% &amp; thpt &lt;5 Mbps · rural: PRB ≥92% &amp; thpt &lt;3 Mbps)
        </div>
        <DataTable columns={congestedColumns} rows={congestedRows} emptyMessage="No congested sectors." />
      </GlassPanel>
    </div>
  )
}

function StatTile({ value, label, tone }: { value: number; label: string; tone?: 'danger' | 'success' }) {
  const toneClass =
    tone === 'danger' ? 'text-red-300' : tone === 'success' ? 'text-green-300' : 'text-white'
  return (
    <div className="min-w-[110px] flex-1 rounded-2xl bg-white/6 px-3 py-2.5">
      <p className={`font-display text-lg font-semibold ${toneClass}`}>{value}</p>
      <p className="text-[11px] text-white/55">{label}</p>
    </div>
  )
}

function LegendItem({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block h-3 w-3 rounded ${color}`} />
      {label}
    </span>
  )
}
