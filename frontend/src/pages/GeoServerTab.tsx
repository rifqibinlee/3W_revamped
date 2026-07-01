import { useEffect, useState } from 'react'
import { GlassPanel } from '../components/GlassPanel'
import { api, ApiError, type GsLayer, type GsStyle } from '../lib/api'

// ── tiny helpers ─────────────────────────────────────────────────────────────

function Badge({ on }: { on: boolean }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${on ? 'bg-green-400/15 text-green-300' : 'bg-white/10 text-white/40'}`}>
      {on ? 'visible' : 'hidden'}
    </span>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <p className="mb-3.5 font-display text-sm font-semibold">{children}</p>
}

// ── SLD editor modal ──────────────────────────────────────────────────────────

function StyleEditorModal({
  style,
  onClose,
}: {
  style: GsStyle
  onClose: () => void
}) {
  const [sld, setSld] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.gsStyleSld(style.name, style.workspace ?? undefined)
      .then((r) => { setSld(r.sld); setLoading(false) })
      .catch((e) => { setError(e instanceof ApiError ? e.message : 'Failed to load SLD'); setLoading(false) })
  }, [style.name, style.workspace])

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      await api.gsUpdateStyleSld(style.name, sld, style.workspace ?? undefined)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/70 backdrop-blur-sm">
      <GlassPanel className="flex w-full max-w-2xl flex-col gap-3">
        <div className="flex items-center justify-between">
          <p className="font-display text-sm font-semibold">
            Edit SLD — {style.workspace ? `${style.workspace}:` : ''}{style.name}
          </p>
          <button onClick={onClose} className="text-white/40 hover:text-white/80">
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        {error && <p className="text-xs text-red-300">{error}</p>}
        {loading ? (
          <p className="text-sm text-white/50">Loading SLD…</p>
        ) : (
          <textarea
            value={sld}
            onChange={(e) => setSld(e.target.value)}
            rows={22}
            spellCheck={false}
            className="w-full rounded-xl border border-white/15 bg-ink-950/60 p-3 font-mono text-xs text-white/85 focus:border-sky-400/60 focus:outline-none"
          />
        )}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded-xl border border-white/20 px-4 py-2 text-sm text-white/70 hover:bg-white/5">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || loading}
            className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-ink-900 disabled:opacity-60"
          >
            {saving ? 'Saving…' : saved ? 'Saved ✓' : 'Save SLD'}
          </button>
        </div>
      </GlassPanel>
    </div>
  )
}

// ── create style modal ────────────────────────────────────────────────────────

function CreateStyleModal({ workspaces, onClose, onCreated }: { workspaces: string[]; onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('')
  const [workspace, setWorkspace] = useState('')
  const [sld, setSld] = useState(`<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
  xsi:schemaLocation="http://www.opengis.net/sld StyledLayerDescriptor.xsd"
  xmlns="http://www.opengis.net/sld"
  xmlns:ogc="http://www.opengis.net/ogc"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <NamedLayer>
    <Name>new_style</Name>
    <UserStyle>
      <Title>New style</Title>
      <FeatureTypeStyle>
        <Rule>
          <PolygonSymbolizer>
            <Fill><CssParameter name="fill">#aaddff</CssParameter></Fill>
            <Stroke><CssParameter name="stroke">#0055aa</CssParameter></Stroke>
          </PolygonSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>`)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleCreate() {
    if (!name.trim()) { setError('Style name is required'); return }
    setSaving(true)
    setError(null)
    try {
      await api.gsCreateStyle(name.trim(), sld, workspace || undefined)
      onCreated()
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Create failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/70 backdrop-blur-sm">
      <GlassPanel className="flex w-full max-w-2xl flex-col gap-3">
        <div className="flex items-center justify-between">
          <p className="font-display text-sm font-semibold">New style</p>
          <button onClick={onClose} className="text-white/40 hover:text-white/80">
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        {error && <p className="text-xs text-red-300">{error}</p>}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wider text-white/45">Style name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my_style"
              className="w-full rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-sm focus:border-sky-400/60 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wider text-white/45">Workspace (optional)</label>
            <select
              value={workspace}
              onChange={(e) => setWorkspace(e.target.value)}
              className="w-full rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-sm focus:border-sky-400/60 focus:outline-none"
            >
              <option value="" className="bg-ink-900">Global</option>
              {workspaces.map((w) => <option key={w} value={w} className="bg-ink-900">{w}</option>)}
            </select>
          </div>
        </div>
        <textarea
          value={sld}
          onChange={(e) => setSld(e.target.value)}
          rows={18}
          spellCheck={false}
          className="w-full rounded-xl border border-white/15 bg-ink-950/60 p-3 font-mono text-xs text-white/85 focus:border-sky-400/60 focus:outline-none"
        />
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded-xl border border-white/20 px-4 py-2 text-sm text-white/70 hover:bg-white/5">
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={saving}
            className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-ink-900 disabled:opacity-60"
          >
            {saving ? 'Creating…' : 'Create style'}
          </button>
        </div>
      </GlassPanel>
    </div>
  )
}

// ── publish modal ─────────────────────────────────────────────────────────────

function PublishModal({ workspaces, onClose, onPublished }: { workspaces: string[]; onClose: () => void; onPublished: () => void }) {
  const [workspace, setWorkspace] = useState(workspaces[0] ?? '')
  const [datastores, setDatastores] = useState<string[]>([])
  const [datastore, setDatastore] = useState('')
  const [featureTypes, setFeatureTypes] = useState<string[]>([])
  const [nativeName, setNativeName] = useState('')
  const [title, setTitle] = useState('')
  const [loading, setLoading] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!workspace) return
    setDatastores([])
    setDatastore('')
    setFeatureTypes([])
    api.gsDatastores(workspace)
      .then((ds) => { setDatastores(ds.map((d) => d.name)); setDatastore(ds[0]?.name ?? '') })
      .catch(() => setDatastores([]))
  }, [workspace])

  useEffect(() => {
    if (!workspace || !datastore) return
    setLoading(true)
    setFeatureTypes([])
    api.gsAvailableFeatureTypes(workspace, datastore)
      .then((fts) => { setFeatureTypes(fts); setNativeName(fts[0] ?? '') })
      .catch(() => setFeatureTypes([]))
      .finally(() => setLoading(false))
  }, [workspace, datastore])

  async function handlePublish() {
    if (!nativeName) { setError('Select a feature type'); return }
    setPublishing(true)
    setError(null)
    try {
      await api.gsPublish(workspace, datastore, nativeName, title || nativeName)
      onPublished()
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Publish failed')
    } finally {
      setPublishing(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/70 backdrop-blur-sm">
      <GlassPanel className="w-full max-w-md space-y-3">
        <div className="flex items-center justify-between">
          <p className="font-display text-sm font-semibold">Publish layer</p>
          <button onClick={onClose} className="text-white/40 hover:text-white/80">
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        {error && <p className="text-xs text-red-300">{error}</p>}
        <div className="space-y-2">
          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wider text-white/45">Workspace</label>
            <select value={workspace} onChange={(e) => setWorkspace(e.target.value)}
              className="w-full rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-sm focus:border-sky-400/60 focus:outline-none">
              {workspaces.map((w) => <option key={w} value={w} className="bg-ink-900">{w}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wider text-white/45">Datastore</label>
            <select value={datastore} onChange={(e) => setDatastore(e.target.value)}
              className="w-full rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-sm focus:border-sky-400/60 focus:outline-none">
              {datastores.length === 0 && <option className="bg-ink-900">No datastores</option>}
              {datastores.map((d) => <option key={d} value={d} className="bg-ink-900">{d}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wider text-white/45">
              Feature type {loading && '(loading…)'}
            </label>
            <select value={nativeName} onChange={(e) => setNativeName(e.target.value)}
              className="w-full rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-sm focus:border-sky-400/60 focus:outline-none">
              {featureTypes.length === 0 && <option className="bg-ink-900">{loading ? 'Loading…' : 'None available'}</option>}
              {featureTypes.map((ft) => <option key={ft} value={ft} className="bg-ink-900">{ft}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wider text-white/45">Title (optional)</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={nativeName || 'Layer title'}
              className="w-full rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-sm focus:border-sky-400/60 focus:outline-none" />
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded-xl border border-white/20 px-4 py-2 text-sm text-white/70 hover:bg-white/5">
            Cancel
          </button>
          <button onClick={handlePublish} disabled={publishing || loading || !nativeName}
            className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-ink-900 disabled:opacity-60">
            {publishing ? 'Publishing…' : 'Publish'}
          </button>
        </div>
      </GlassPanel>
    </div>
  )
}

// ── main component ────────────────────────────────────────────────────────────

export function GeoServerTab() {
  const [layers, setLayers] = useState<GsLayer[]>([])
  const [styles, setStyles] = useState<GsStyle[]>([])
  const [workspaces, setWorkspaces] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)

  const [editStyle, setEditStyle] = useState<GsStyle | null>(null)
  const [showCreateStyle, setShowCreateStyle] = useState(false)
  const [showPublish, setShowPublish] = useState(false)

  // layer-level inline style selector open state
  const [openStylePicker, setOpenStylePicker] = useState<string | null>(null)
  const [layerSearch, setLayerSearch] = useState('')
  const [styleSearch, setStyleSearch] = useState('')

  function loadAll() {
    setLoading(true)
    setError(null)
    Promise.all([api.gsLayers(), api.gsStyles(), api.gsWorkspaces()])
      .then(([l, s, w]) => {
        setLayers(l)
        setStyles(s)
        setWorkspaces(w.map((ws) => ws.name))
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Could not connect to GeoServer'))
      .finally(() => setLoading(false))
  }

  useEffect(loadAll, [])

  async function toggleLayer(layer: GsLayer) {
    const next = !layer.enabled
    setLayers((prev) => prev.map((l) => l.name === layer.name ? { ...l, enabled: next } : l))
    try {
      await api.gsUpdateLayer(layer.name, { enabled: next })
      setStatus(`${layer.name} ${next ? 'visible' : 'hidden'}`)
    } catch (e) {
      setLayers((prev) => prev.map((l) => l.name === layer.name ? { ...l, enabled: !next } : l))
      setStatus(null)
      setError(e instanceof ApiError ? e.message : 'Update failed')
    }
  }

  async function changeStyle(layer: GsLayer, styleName: string) {
    setLayers((prev) => prev.map((l) => l.name === layer.name ? { ...l, default_style: styleName } : l))
    setOpenStylePicker(null)
    try {
      await api.gsUpdateLayer(layer.name, { default_style: styleName })
      setStatus(`Style updated for ${layer.name}`)
    } catch (e) {
      setLayers((prev) => prev.map((l) => l.name === layer.name ? { ...l, default_style: layer.default_style } : l))
      setError(e instanceof ApiError ? e.message : 'Style update failed')
    }
  }

  const filteredLayers = layers.filter((l) =>
    !layerSearch || l.name.toLowerCase().includes(layerSearch.toLowerCase()) || l.title.toLowerCase().includes(layerSearch.toLowerCase())
  )
  const filteredStyles = styles.filter((s) =>
    !styleSearch || s.name.toLowerCase().includes(styleSearch.toLowerCase())
  )

  if (loading) {
    return (
      <GlassPanel>
        <p className="text-sm text-white/50">Connecting to GeoServer…</p>
      </GlassPanel>
    )
  }

  if (error && layers.length === 0) {
    return (
      <GlassPanel className="border-red-400/30 bg-red-400/5">
        <p className="mb-1 font-display text-sm font-semibold text-red-300">GeoServer unreachable</p>
        <p className="text-xs text-white/60">{error}</p>
        <button onClick={loadAll} className="mt-3 rounded-xl border border-white/20 px-3 py-1.5 text-xs text-white/70 hover:bg-white/5">
          Retry
        </button>
      </GlassPanel>
    )
  }

  return (
    <div className="space-y-4">
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

      {/* Layers */}
      <GlassPanel>
        <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
          <SectionTitle>Layers ({layers.length})</SectionTitle>
          <div className="flex items-center gap-2">
            <input
              value={layerSearch}
              onChange={(e) => setLayerSearch(e.target.value)}
              placeholder="Search layers…"
              className="rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs focus:border-sky-400/60 focus:outline-none"
            />
            <button
              onClick={() => setShowPublish(true)}
              className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-3 py-1.5 text-xs font-semibold text-ink-900"
            >
              Publish layer
            </button>
            <button onClick={loadAll} title="Refresh" className="flex h-7 w-7 items-center justify-center rounded-lg border border-white/20 text-white/60 hover:bg-white/5">
              <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M1 4v6h6M23 20v-6h-6" /><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15" />
              </svg>
            </button>
          </div>
        </div>

        {filteredLayers.length === 0 ? (
          <p className="text-sm text-white/50">{layerSearch ? 'No matching layers.' : 'No layers published yet.'}</p>
        ) : (
          <div className="divide-y divide-white/8">
            {filteredLayers.map((layer) => (
              <div key={layer.name} className="py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-3">
                  {/* visibility toggle */}
                  <button
                    onClick={() => toggleLayer(layer)}
                    title={layer.enabled ? 'Click to hide' : 'Click to show'}
                    className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${layer.enabled ? 'bg-green-400' : 'bg-white/20'}`}
                  >
                    <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${layer.enabled ? 'translate-x-4' : 'translate-x-0.5'}`} />
                  </button>

                  {/* name + title */}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">{layer.title || layer.name}</p>
                    <p className="truncate text-[11px] text-white/45">{layer.name}</p>
                  </div>

                  <Badge on={layer.enabled} />

                  {/* style picker */}
                  <div className="relative">
                    <button
                      onClick={() => setOpenStylePicker(openStylePicker === layer.name ? null : layer.name)}
                      className="flex items-center gap-1.5 rounded-lg border border-white/20 px-2.5 py-1 text-xs text-white/70 hover:bg-white/5"
                    >
                      <span>{layer.default_style || 'no style'}</span>
                      <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M6 9l6 6 6-6" />
                      </svg>
                    </button>
                    {openStylePicker === layer.name && (
                      <div className="absolute right-0 top-full z-20 mt-1 max-h-52 w-52 overflow-y-auto rounded-xl border border-white/20 bg-ink-950 shadow-xl">
                        {styles.map((s) => (
                          <button
                            key={`${s.workspace}:${s.name}`}
                            onClick={() => changeStyle(layer, s.workspace ? `${s.workspace}:${s.name}` : s.name)}
                            className={`flex w-full items-center justify-between px-3 py-2 text-left text-xs hover:bg-white/8 ${layer.default_style === s.name ? 'text-sky-300' : 'text-white/80'}`}
                          >
                            <span>{s.name}</span>
                            {s.workspace && <span className="text-white/35">{s.workspace}</span>}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                {layer.abstract && (
                  <p className="mt-1 pl-12 text-[11px] text-white/40 line-clamp-2">{layer.abstract}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </GlassPanel>

      {/* Styles */}
      <GlassPanel>
        <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
          <SectionTitle>Styles ({styles.length})</SectionTitle>
          <div className="flex items-center gap-2">
            <input
              value={styleSearch}
              onChange={(e) => setStyleSearch(e.target.value)}
              placeholder="Search styles…"
              className="rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs focus:border-sky-400/60 focus:outline-none"
            />
            <button
              onClick={() => setShowCreateStyle(true)}
              className="rounded-xl border border-white/20 px-3 py-1.5 text-xs text-white/70 hover:bg-white/5"
            >
              + New style
            </button>
          </div>
        </div>

        <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
          {filteredStyles.map((s) => (
            <button
              key={`${s.workspace ?? ''}:${s.name}`}
              onClick={() => setEditStyle(s)}
              className="flex items-center justify-between rounded-xl border border-white/10 px-3 py-2.5 text-left hover:border-white/25 hover:bg-white/5"
            >
              <span className="text-sm font-medium">{s.name}</span>
              <span className="text-[10px] text-white/35">{s.workspace ?? 'global'}</span>
            </button>
          ))}
          {filteredStyles.length === 0 && (
            <p className="col-span-3 text-sm text-white/50">{styleSearch ? 'No matching styles.' : 'No styles found.'}</p>
          )}
        </div>
      </GlassPanel>

      {/* Modals */}
      {editStyle && <StyleEditorModal style={editStyle} onClose={() => setEditStyle(null)} />}
      {showCreateStyle && (
        <CreateStyleModal
          workspaces={workspaces}
          onClose={() => setShowCreateStyle(false)}
          onCreated={loadAll}
        />
      )}
      {showPublish && (
        <PublishModal
          workspaces={workspaces}
          onClose={() => setShowPublish(false)}
          onPublished={() => { loadAll(); setStatus('Layer published successfully') }}
        />
      )}
    </div>
  )
}
