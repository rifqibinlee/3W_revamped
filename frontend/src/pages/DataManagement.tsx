import { useEffect, useRef, useState } from 'react'
import { DataTable, type Column } from '../components/DataTable'
import { GlassPanel } from '../components/GlassPanel'
import { api, ApiError, type DataCategory, type DataFile, type DataFilePreview } from '../lib/api'

function isoWeek(d: Date): string {
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
  const dayNum = date.getUTCDay() || 7
  date.setUTCDate(date.getUTCDate() + 4 - dayNum)
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1))
  const week = Math.ceil(((date.getTime() - yearStart.getTime()) / 86400000 + 1) / 7)
  return `${date.getUTCFullYear()}-W${String(week).padStart(2, '0')}`
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function DataManagement() {
  const [categories, setCategories] = useState<DataCategory[]>([])
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [weeks, setWeeks] = useState<string[]>([])
  const [selectedWeek, setSelectedWeek] = useState<string | null>(null)
  const [newWeek, setNewWeek] = useState(isoWeek(new Date()))
  const [files, setFiles] = useState<DataFile[]>([])
  const [preview, setPreview] = useState<{ filename: string; data: DataFilePreview } | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  function loadCategories() {
    api.listDataCategories().then(setCategories).catch(() => setError('Could not load categories'))
  }

  useEffect(loadCategories, [])

  const category = categories.find((c) => c.key === selectedCategory) ?? null

  useEffect(() => {
    if (!selectedCategory) return
    Promise.resolve().then(() => setPreview(null))
    if (category?.weekly) {
      api.listDataWeeks(selectedCategory).then((ws) => {
        setWeeks(ws)
        setSelectedWeek(ws[0] ?? null)
      })
    } else {
      Promise.resolve().then(() => {
        setWeeks([])
        setSelectedWeek(null)
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCategory])

  useEffect(() => {
    if (!selectedCategory) return
    if (category?.weekly && !selectedWeek) {
      Promise.resolve().then(() => setFiles([]))
      return
    }
    api
      .listDataFiles(selectedCategory, category?.weekly ? selectedWeek ?? undefined : undefined)
      .then(setFiles)
      .catch(() => setFiles([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCategory, selectedWeek])

  function refreshFiles() {
    if (!selectedCategory) return
    if (category?.weekly && !selectedWeek) {
      setFiles([])
      return
    }
    api
      .listDataFiles(selectedCategory, category?.weekly ? selectedWeek ?? undefined : undefined)
      .then(setFiles)
      .catch(() => setFiles([]))
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !selectedCategory) return
    const week = category?.weekly ? newWeek : undefined
    try {
      await api.uploadDataFile(selectedCategory, file, week)
      setStatus(`Uploaded ${file.name}`)
      loadCategories()
      if (category?.weekly) {
        const ws = await api.listDataWeeks(selectedCategory)
        setWeeks(ws)
        setSelectedWeek(week ?? ws[0] ?? null)
      } else {
        refreshFiles()
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Upload failed')
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  async function handleDelete(filename: string) {
    if (!selectedCategory) return
    try {
      await api.deleteDataFile(selectedCategory, filename, category?.weekly ? selectedWeek ?? undefined : undefined)
      setPreview(null)
      refreshFiles()
      loadCategories()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not delete file')
    }
  }

  async function handlePreview(filename: string) {
    if (!selectedCategory) return
    try {
      const data = await api.previewDataFile(selectedCategory, filename, category?.weekly ? selectedWeek ?? undefined : undefined)
      setPreview({ filename, data })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not preview file')
    }
  }

  async function handleRunPipeline() {
    setRunning(true)
    setStatus(null)
    setError(null)
    try {
      const result = await api.runDataPipeline(true)
      setStatus(
        result.stages_run.length > 0
          ? `Ran: ${result.stages_run.join(', ')}${result.stages_skipped.length ? ` — skipped: ${result.stages_skipped.join('; ')}` : ''}`
          : `Nothing to run — ${result.stages_skipped.join('; ')}`,
      )
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Pipeline run failed')
    } finally {
      setRunning(false)
    }
  }

  const fileColumns: Column<DataFile>[] = [
    { key: 'filename', label: 'Filename' },
    { key: 'size_bytes', label: 'Size', render: (f) => fmtBytes(f.size_bytes) },
    { key: 'modified_at', label: 'Uploaded', render: (f) => new Date(f.modified_at).toLocaleString() },
    {
      key: 'actions',
      label: '',
      render: (f) => (
        <div className="flex gap-2">
          <button onClick={() => handlePreview(f.filename)} className="rounded-full border border-white/20 px-3 py-1 text-xs text-white/80 hover:bg-white/10">
            View
          </button>
          <button onClick={() => handleDelete(f.filename)} className="rounded-full border border-white/20 px-3 py-1 text-xs text-red-300 hover:bg-white/10">
            Delete
          </button>
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <GlassPanel className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-display text-lg font-semibold">Data management</p>
          <p className="mt-1 text-sm text-white/60">
            Upload raw source files by category, then run the ETL pipeline to refresh the analytics data.
          </p>
        </div>
        <button
          onClick={handleRunPipeline}
          disabled={running}
          className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-5 py-2.5 text-sm font-semibold text-ink-900 disabled:opacity-60"
        >
          {running ? 'Running pipeline…' : 'Run ETL pipeline'}
        </button>
      </GlassPanel>

      {status && (
        <GlassPanel className="border-green-400/30 bg-green-400/5">
          <p className="text-sm text-green-200">{status}</p>
        </GlassPanel>
      )}
      {error && (
        <GlassPanel className="border-red-400/30 bg-red-400/5">
          <p className="text-sm text-red-300">{error}</p>
        </GlassPanel>
      )}

      <div className="grid gap-4 md:grid-cols-[260px_1fr]">
        <GlassPanel>
          <p className="mb-3.5 font-display text-sm font-semibold">Directories</p>
          <div className="space-y-1">
            {categories.map((c) => (
              <button
                key={c.key}
                onClick={() => setSelectedCategory(c.key)}
                className={`flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-left text-sm ${
                  selectedCategory === c.key ? 'bg-white/10 text-white' : 'text-white/70 hover:bg-white/5'
                }`}
              >
                <span className="flex min-w-0 flex-1 items-center gap-2">
                  <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                  </svg>
                  <span className="truncate">{c.label}</span>
                </span>
                <span className="ml-2 shrink-0 rounded-full bg-white/10 px-2 py-0.5 text-xs text-white/50">{c.file_count}</span>
              </button>
            ))}
          </div>
        </GlassPanel>

        <div className="space-y-4">
          {!selectedCategory && (
            <GlassPanel>
              <p className="text-sm text-white/50">Select a directory to view or upload files.</p>
            </GlassPanel>
          )}

          {selectedCategory && (
            <GlassPanel>
              <div className="mb-3.5 flex flex-wrap items-end justify-between gap-3">
                <p className="font-display text-sm font-semibold">{category?.label}</p>
                <div className="flex flex-wrap items-end gap-2">
                  {category?.weekly && (
                    <>
                      <select
                        value={selectedWeek ?? ''}
                        onChange={(e) => setSelectedWeek(e.target.value || null)}
                        className="rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs focus:border-sky-400/60 focus:outline-none"
                      >
                        <option value="" className="bg-ink-900">
                          Select week…
                        </option>
                        {weeks.map((w) => (
                          <option key={w} value={w} className="bg-ink-900">
                            {w}
                          </option>
                        ))}
                      </select>
                      <input
                        type="text"
                        value={newWeek}
                        onChange={(e) => setNewWeek(e.target.value)}
                        placeholder="2026-W13"
                        title="Week to upload into (creates if new)"
                        className="w-24 rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs focus:border-sky-400/60 focus:outline-none"
                      />
                    </>
                  )}
                  <input ref={fileInputRef} type="file" onChange={handleUpload} className="hidden" id="data-upload-input" />
                  <label
                    htmlFor="data-upload-input"
                    className="cursor-pointer rounded-lg bg-gradient-to-r from-accent-400 to-accent-500 px-3 py-1.5 text-xs font-semibold text-ink-900"
                  >
                    Upload file
                  </label>
                </div>
              </div>

              <DataTable columns={fileColumns} rows={files} emptyMessage="No files in this directory yet." />
            </GlassPanel>
          )}

          {preview && (
            <GlassPanel>
              <div className="mb-3.5 flex items-center justify-between">
                <p className="font-display text-sm font-semibold">{preview.filename}</p>
                <button onClick={() => setPreview(null)} className="text-xs text-white/50 hover:text-white/80">
                  Close
                </button>
              </div>
              <div className="max-h-[50vh] overflow-auto">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-ink-900">
                    <tr className="border-b border-white/10 uppercase tracking-wider text-white/45">
                      {preview.data.columns.map((c) => (
                        <th key={c} className="whitespace-nowrap px-3 py-2 font-medium">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/8">
                    {preview.data.rows.map((row, i) => (
                      <tr key={i} className="hover:bg-white/4">
                        {row.map((cell, j) => (
                          <td key={j} className="whitespace-nowrap px-3 py-2 text-white/85">
                            {cell === null ? '—' : String(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {preview.data.truncated && (
                <p className="mt-2 text-xs text-white/45">Showing the first {preview.data.rows.length} rows.</p>
              )}
            </GlassPanel>
          )}
        </div>
      </div>
    </div>
  )
}
