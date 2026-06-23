import { useEffect, useState } from 'react'
import { GlassPanel } from '../components/GlassPanel'
import { api, ApiError, type CapexPricing } from '../lib/api'
import { useAuth } from '../lib/useAuth'

export function Pricing() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [pricing, setPricing] = useState<CapexPricing | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ category: string; item: string } | null>(null)
  const [priceInput, setPriceInput] = useState('')
  const [minInput, setMinInput] = useState('')
  const [maxInput, setMaxInput] = useState('')
  const [saving, setSaving] = useState(false)

  function load() {
    api.capexPricing().then(setPricing).catch(() => setError('Could not load pricing'))
  }

  useEffect(load, [])

  function startEdit(category: string, item: string) {
    const current = pricing?.[category]?.[item]
    setEditing({ category, item })
    setPriceInput(current?.price != null ? String(current.price) : '')
    setMinInput(current ? String(current.price_min) : '')
    setMaxInput(current ? String(current.price_max) : '')
  }

  async function handleSave() {
    if (!editing) return
    const price = Number(priceInput)
    if (!Number.isFinite(price) || price <= 0) {
      setError('Enter a valid price')
      return
    }
    setSaving(true)
    try {
      const min = minInput ? Number(minInput) : undefined
      const max = maxInput ? Number(maxInput) : undefined
      await api.upsertCapexPrice(editing.category, editing.item, { price, price_min: min, price_max: max })
      setEditing(null)
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save price')
    } finally {
      setSaving(false)
    }
  }

  if (!pricing) return <p className="text-sm text-white/60">Loading…</p>

  return (
    <div className="space-y-4">
      <GlassPanel>
        <p className="font-display text-lg font-semibold">CAPEX pricing</p>
        <p className="mt-1 text-sm text-white/60">
          {isAdmin
            ? 'You see and edit the exact negotiated price for each upgrade item.'
            : 'You see the budget range for each upgrade item — exact pricing is admin-only.'}
        </p>
        {error && <p className="mt-2 text-sm text-red-300">{error}</p>}
      </GlassPanel>

      {Object.entries(pricing).map(([category, items]) => (
        <GlassPanel key={category}>
          <p className="mb-3.5 font-display text-sm font-semibold">{category === 'EQ' ? 'Equipment (EQ)' : 'Equipment + Service (ES)'}</p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-white/45">
                  <th className="px-3 py-2 font-medium">Item</th>
                  {isAdmin && <th className="px-3 py-2 font-medium">Exact price</th>}
                  <th className="px-3 py-2 font-medium">Range</th>
                  {isAdmin && <th className="px-3 py-2 font-medium" />}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/8">
                {Object.entries(items).map(([itemName, item]) => (
                  <tr key={itemName} className="hover:bg-white/4">
                    <td className="px-3 py-2.5 text-white/85">{itemName}</td>
                    {isAdmin && <td className="px-3 py-2.5">{item.price != null ? `RM ${item.price.toLocaleString()}` : '—'}</td>}
                    <td className="px-3 py-2.5 text-white/70">
                      RM {item.price_min.toLocaleString()} – RM {item.price_max.toLocaleString()}
                    </td>
                    {isAdmin && (
                      <td className="px-3 py-2.5">
                        <button
                          onClick={() => startEdit(category, itemName)}
                          className="rounded-full border border-white/20 px-3 py-1 text-xs text-white/80 hover:bg-white/10"
                        >
                          Edit
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassPanel>
      ))}

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/60 backdrop-blur-sm">
          <GlassPanel className="w-full max-w-sm">
            <p className="mb-3.5 font-display text-sm font-semibold">
              Edit {editing.item} ({editing.category})
            </p>
            <div className="mb-3">
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
                Exact price (RM)
              </label>
              <input
                type="number"
                autoFocus
                value={priceInput}
                onChange={(e) => setPriceInput(e.target.value)}
                className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm focus:border-sky-400/60 focus:outline-none"
              />
            </div>
            <div className="mb-3 flex gap-2">
              <div className="flex-1">
                <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
                  Range min
                </label>
                <input
                  type="number"
                  value={minInput}
                  onChange={(e) => setMinInput(e.target.value)}
                  className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm focus:border-sky-400/60 focus:outline-none"
                />
              </div>
              <div className="flex-1">
                <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
                  Range max
                </label>
                <input
                  type="number"
                  value={maxInput}
                  onChange={(e) => setMaxInput(e.target.value)}
                  className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm focus:border-sky-400/60 focus:outline-none"
                />
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setEditing(null)}
                className="rounded-xl border border-white/20 px-4 py-2 text-sm font-semibold text-white/75"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-ink-900 disabled:opacity-60"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </GlassPanel>
        </div>
      )}
    </div>
  )
}
