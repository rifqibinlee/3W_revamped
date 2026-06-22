import type { AnalyticsFilters, FilterOptions } from '../lib/api'

interface FilterBarProps {
  options: FilterOptions
  filters: AnalyticsFilters
  onChange: (filters: AnalyticsFilters) => void
}

export function FilterBar({ options, filters, onChange }: FilterBarProps) {
  return (
    <div className="flex flex-wrap gap-3">
      <Select
        label="Region"
        value={filters.region ?? 'All'}
        onChange={(v) => onChange({ ...filters, region: v })}
        options={['All', ...options.regions]}
      />
      <Select
        label="Year"
        value={filters.year?.toString() ?? 'All'}
        onChange={(v) => onChange({ ...filters, year: v === 'All' ? undefined : Number(v) })}
        options={['All', ...options.years.map(String)]}
      />
      <Select
        label="Week"
        value={filters.week?.toString() ?? 'All'}
        onChange={(v) => onChange({ ...filters, week: v === 'All' ? undefined : Number(v) })}
        options={['All', ...options.weeks.map(String)]}
      />
      <Select
        label="Operator"
        value={filters.operator ?? 'All'}
        onChange={(v) => onChange({ ...filters, operator: v })}
        options={['All', ...options.operators]}
      />
      <div className="min-w-[130px] flex-1">
        <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
          Cluster
        </label>
        <input
          type="text"
          placeholder="e.g. KUL_01"
          value={filters.cluster ?? ''}
          onChange={(e) => onChange({ ...filters, cluster: e.target.value || undefined })}
          className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
        />
      </div>
    </div>
  )
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: string[]
}) {
  return (
    <div className="min-w-[110px] flex-1">
      <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm focus:border-sky-400/60 focus:outline-none"
      >
        {options.map((o) => (
          <option key={o} value={o} className="bg-ink-900">
            {o}
          </option>
        ))}
      </select>
    </div>
  )
}
