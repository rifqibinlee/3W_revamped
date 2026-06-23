import { useCallback, useEffect, useMemo, useState } from 'react'
import { DataTable, type Column } from '../components/DataTable'
import { FilterBar } from '../components/FilterBar'
import { GlassPanel } from '../components/GlassPanel'
import { Pagination } from '../components/Pagination'
import {
  api,
  type AnalyticsFilters,
  type FilterOptions,
  type ForecastRow,
  type SectorMetricRow,
  type SummaryStats,
  type TaskOut,
} from '../lib/api'

const PAGE_SIZE = 12

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

type TabKey = 'sectors' | 'forecast' | 'congested'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'sectors', label: 'Sector performance metrics' },
  { key: 'forecast', label: 'Future forecasts' },
  { key: 'congested', label: 'Congested sectors' },
]

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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [activeTab, setActiveTab] = useState<TabKey>('sectors')
  const [pages, setPages] = useState<Record<TabKey, number>>({ sectors: 0, forecast: 0, congested: 0 })

  const [sectorResult, setSectorResult] = useState({ rows: [] as SectorMetricRow[], total: 0 })
  const [congestedResult, setCongestedResult] = useState({ rows: [] as SectorMetricRow[], total: 0 })
  const [forecastResult, setForecastResult] = useState({ rows: [] as ForecastRow[], total: 0 })

  useEffect(() => {
    Promise.all([api.ganttRows(), api.filterOptions()])
      .then(([gantt, filterOptions]) => {
        setTasks(gantt)
        setOptions(filterOptions)
      })
      .catch(() => setError('Could not load dashboard data'))
      .finally(() => setLoading(false))
  }, [])

  const setPage = (tab: TabKey, page: number) => setPages((prev) => ({ ...prev, [tab]: page }))

  // Filters change -> reset all tab pages to the start and refetch the summary tile
  useEffect(() => {
    Promise.resolve().then(() => setPages({ sectors: 0, forecast: 0, congested: 0 }))
    api.summary(filters).then(setSummary).catch(() => setError('Could not load analytics data'))
  }, [filters])

  const page = pages[activeTab]

  const refreshActiveTab = useCallback(() => {
    const pageArg = { limit: PAGE_SIZE, offset: page * PAGE_SIZE }
    if (activeTab === 'sectors') {
      api.sectorMetrics(filters, pageArg).then(setSectorResult).catch(() => setError('Could not load analytics data'))
    } else if (activeTab === 'forecast') {
      api.forecastTable(filters, pageArg).then(setForecastResult).catch(() => setError('Could not load analytics data'))
    } else {
      api.congestedSectors(filters, pageArg).then(setCongestedResult).catch(() => setError('Could not load analytics data'))
    }
  }, [activeTab, filters, page])

  useEffect(refreshActiveTab, [refreshActiveTab])

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
        <div className="mb-3.5 flex flex-wrap gap-1.5 border-b border-white/10 pb-3.5">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className={`rounded-xl px-3.5 py-2 text-sm font-semibold ${
                activeTab === t.key ? 'bg-sky-400 text-ink-900' : 'text-white/70 hover:bg-white/5'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {activeTab === 'sectors' && (
          <>
            <p className="mb-3.5 text-xs text-white/55">Weekly aggregated performance indicators across all sectors.</p>
            <DataTable columns={sectorColumns} rows={sectorResult.rows} emptyMessage="No sector data — run the ETL pipeline first." />
            <Pagination page={page} pageSize={PAGE_SIZE} total={sectorResult.total} onPageChange={(p) => setPage('sectors', p)} />
          </>
        )}

        {activeTab === 'forecast' && (
          <>
            <p className="mb-3.5 text-xs text-white/55">52-week predictions per sector.</p>
            <div className="mb-3.5 flex flex-wrap items-center gap-4 text-xs text-white/60">
              <span className="font-medium text-white/80">Legend</span>
              <LegendItem color="bg-white/70" label="Actual" />
              <LegendItem color="border border-dashed border-green-400" label="Forecast (vol)" />
              <LegendItem color="border border-dashed border-accent-400" label="Forecast (PRB)" />
              <LegendItem color="border border-dashed border-sky-400" label="Forecast (thpt)" />
            </div>
            <DataTable columns={forecastColumns} rows={forecastResult.rows} emptyMessage="No forecast data — run forecast_results first." />
            <Pagination page={page} pageSize={PAGE_SIZE} total={forecastResult.total} onPageChange={(p) => setPage('forecast', p)} />
          </>
        )}

        {activeTab === 'congested' && (
          <>
            <div className="mb-3.5 rounded-xl border border-red-400/30 bg-red-500/10 p-3 text-xs text-red-200">
              <strong>Congestion criteria</strong> (urban/KMC + NIC: PRB ≥80% &amp; thpt &lt;7 Mbps · urban/KMC: PRB
              ≥80% &amp; thpt &lt;5 Mbps · rural: PRB ≥92% &amp; thpt &lt;3 Mbps)
            </div>
            <DataTable columns={congestedColumns} rows={congestedResult.rows} emptyMessage="No congested sectors." />
            <Pagination page={page} pageSize={PAGE_SIZE} total={congestedResult.total} onPageChange={(p) => setPage('congested', p)} />
          </>
        )}
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
