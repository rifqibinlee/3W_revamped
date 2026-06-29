import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { GlassPanel } from '../components/GlassPanel'
import { api, ApiError, type AnnotationOut, type ProjectOut } from '../lib/api'
import { addCoverageHolesLayer, addStatusLayer, fitMapToAnnotations, getSatelliteStyle } from '../lib/mapLayers'

const DEFAULT_CENTER: [number, number] = [101.5, 3.1]

export function Notes() {
  const [notes, setNotes] = useState<ProjectOut[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [annotations, setAnnotations] = useState<AnnotationOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [creating, setCreating] = useState(false)

  const mapRef = useRef<maplibregl.Map | null>(null)

  function load() {
    api
      .listProjects()
      .then((rows) => {
        const onlyNotes = rows.filter((p) => !p.assignee_id)
        setNotes(onlyNotes)
        if (onlyNotes.length > 0 && !selectedId) setSelectedId(onlyNotes[0].id)
      })
      .catch(() => setError('Could not load notes'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const selectedNote = notes.find((n) => n.id === selectedId) ?? null

  useEffect(() => {
    if (!selectedId) return
    api.listAnnotations(selectedId).then(setAnnotations).catch(() => setAnnotations([]))
  }, [selectedId])

  // A ref callback, not useRef + useEffect(..., []) — the page shows a
  // "Loading…" early return on first mount, so the map container div
  // doesn't exist in the DOM on the very first render. A plain
  // useEffect([]) only fires once, right after that first commit, and
  // finds a null ref forever after; a callback ref fires whenever the
  // node actually attaches, even if that's on a later render once
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
      api.currentStatus().then((rows) => addStatusLayer(map, 'note-sites', rows)).catch(() => undefined)
      addCoverageHolesLayer(map).catch(() => undefined)
    })
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const apply = () => {
      fitMapToAnnotations(map, annotations, DEFAULT_CENTER)

      const sourceId = 'note-annotations'
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
      map.addLayer({
        id: `${sourceId}-fill`,
        type: 'fill',
        source: sourceId,
        paint: { 'fill-color': '#facc15', 'fill-opacity': 0.15 },
      })
      map.addLayer({
        id: `${sourceId}-line`,
        type: 'line',
        source: sourceId,
        paint: { 'line-color': '#facc15', 'line-width': 2 },
      })
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

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setCreating(true)
    try {
      const note = await api.createProject({ title, description: description || undefined })
      setTitle('')
      setDescription('')
      load()
      setSelectedId(note.id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create note')
    } finally {
      setCreating(false)
    }
  }

  if (loading) return <p className="text-sm text-white/60">Loading…</p>

  return (
    <div className="grid gap-4 md:grid-cols-[280px_1fr]">
      <div className="space-y-4">
        <GlassPanel>
          <p className="mb-3.5 font-display text-sm font-semibold">New note</p>
          <form onSubmit={handleCreate} className="space-y-2.5">
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              placeholder="Title"
              className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
            />
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Description"
              rows={3}
              className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
            />
            <button
              type="submit"
              disabled={creating}
              className="w-full rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-ink-900 disabled:opacity-60"
            >
              {creating ? 'Creating…' : 'Create note'}
            </button>
          </form>
          {error && <p className="mt-3 text-sm text-red-300">{error}</p>}
        </GlassPanel>

        <GlassPanel>
          <p className="mb-3.5 font-display text-sm font-semibold">Notes ({notes.length})</p>
          {notes.length === 0 ? (
            <p className="text-sm text-white/50">No notes yet.</p>
          ) : (
            <div className="divide-y divide-white/10">
              {notes.map((n) => (
                <button
                  key={n.id}
                  onClick={() => setSelectedId(n.id)}
                  className={`w-full py-2.5 text-left text-sm ${selectedId === n.id ? 'text-white' : 'text-white/70'}`}
                >
                  {n.title}
                </button>
              ))}
            </div>
          )}
        </GlassPanel>
      </div>

      <div className="space-y-4">
        {!selectedNote && (
          <GlassPanel>
            <p className="text-sm text-white/50">Select or create a note.</p>
          </GlassPanel>
        )}

        {selectedNote && (
          <GlassPanel>
            <p className="font-display text-lg font-semibold">{selectedNote.title}</p>
            <p className="mt-2 whitespace-pre-wrap text-sm text-white/75">
              {selectedNote.description || 'No description.'}
            </p>
          </GlassPanel>
        )}

        <div ref={mapContainerRef} className="h-[50vh] w-full overflow-hidden rounded-3xl border border-white/15" />
      </div>
    </div>
  )
}
