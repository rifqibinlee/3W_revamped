import type { ReactNode } from 'react'

export interface Column<T> {
  key: string
  label: string
  render?: (row: T) => ReactNode
}

export function DataTable<T extends object>({
  columns,
  rows,
  emptyMessage = 'No data',
}: {
  columns: Column<T>[]
  rows: T[]
  emptyMessage?: string
}) {
  if (rows.length === 0) {
    return <p className="py-6 text-center text-sm text-white/50">{emptyMessage}</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-white/45">
            {columns.map((col) => (
              <th key={col.key} className="px-3 py-2 font-medium">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-white/8">
          {rows.map((row, i) => (
            <tr key={i} className="hover:bg-white/4">
              {columns.map((col) => (
                <td key={col.key} className="px-3 py-2.5 text-white/85">
                  {col.render ? col.render(row) : String((row as Record<string, unknown>)[col.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
