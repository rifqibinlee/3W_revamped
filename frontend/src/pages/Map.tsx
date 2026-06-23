import type { FeatureCollection, Geometry, Polygon } from 'geojson'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState } from 'react'
import { GlassPanel } from '../components/GlassPanel'
import { api, ApiError, type CurrentStatusRow, type ProjectOut } from '../lib/api'

const STYLE_URL = 'https://demotiles.maplibre.org/style.json'
const DEFAULT_CENTER: [number, number] = [101.5, 3.1]
const DEFAULT_ZOOM = 11

type DrawTool = 'none' | 'point' | 'line' | 'polygon' | 'buffer'

const QUARTER_WEEKS = [13, 26, 39, 52]

function statusGeoJson(rows: CurrentStatusRow[]): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: rows
      .filter((r) => r.latitude != null && r.longitude != null)
      .map((r) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [r.longitude as number, r.latitude as number] },
        properties: { site_id: r.site_id, region: r.region, congested: r.congested },
      })),
  }
}

function circlePolygon(center: [number, number], radiusMeters: number): Polygon {
  const points = 48
  const coords: [number, number][] = []
  const [lng, lat] = center
  const latRad = (lat * Math.PI) / 180
  const metersPerDegLat = 111320
  const metersPerDegLng = 111320 * Math.cos(latRad)
  for (let i = 0; i <= points; i++) {
    const angle = (i / points) * 2 * Math.PI
    coords.push([lng + (radiusMeters * Math.cos(angle)) / metersPerDegLng, lat + (radiusMeters * Math.sin(angle)) / metersPerDegLat])
  }
  return { type: 'Polygon', coordinates: [coords] }
}

function addStatusLayer(map: maplibregl.Map, sourceId: string, rows: CurrentStatusRow[]) {
  const geojson = statusGeoJson(rows)
  const existing = map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined
  if (existing) {
    existing.setData(geojson)
    return
  }
  map.addSource(sourceId, { type: 'geojson', data: geojson })
  map.addLayer({
    id: `${sourceId}-circle`,
    type: 'circle',
    source: sourceId,
    paint: {
      'circle-radius': 6,
      'circle-color': ['case', ['get', 'congested'], '#dc2626', '#3b82f6'],
      'circle-stroke-width': 2,
      'circle-stroke-color': '#ffffff',
    },
  })
  map.on('click', `${sourceId}-circle`, (e) => {
    const f = e.features?.[0]
    if (!f) return
    const props = f.properties as { site_id: string; region: string; congested: boolean }
    new maplibregl.Popup()
      .setLngLat(e.lngLat)
      .setHTML(
        `<strong>${props.site_id}</strong><br/>${props.region}<br/>${props.congested ? '⚠ Congested' : '✓ Normal'}`,
      )
      .addTo(map)
  })
}

export function MapPage() {
  const containerRef = useRef<HTMLDivElement>(null)
  const splitLeftRef = useRef<HTMLDivElement>(null)
  const splitRightRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const splitLeftMapRef = useRef<maplibregl.Map | null>(null)
  const splitRightMapRef = useRef<maplibregl.Map | null>(null)

  const [splitActive, setSplitActive] = useState(false)
  const [forecastYear, setForecastYear] = useState(new Date().getFullYear())
  const [forecastWeek, setForecastWeek] = useState(13)

  const [projects, setProjects] = useState<ProjectOut[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState('')
  const [tool, setTool] = useState<DrawTool>('none')
  const [draftPoints, setDraftPoints] = useState<[number, number][]>([])
  const [status, setStatus] = useState<string | null>(null)

  useEffect(() => {
    api.listProjects().then(setProjects).catch(() => undefined)
  }, [])

  // Single map (non-split mode)
  useEffect(() => {
    if (splitActive || !containerRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE_URL,
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
    })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl(), 'top-right')

    map.on('load', () => {
      api.currentStatus().then((rows) => addStatusLayer(map, 'current-status', rows)).catch(() => undefined)
    })

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [splitActive])

  // Split mode: left = current status, right = forecast
  useEffect(() => {
    if (!splitActive || !splitLeftRef.current || !splitRightRef.current) return

    const left = new maplibregl.Map({
      container: splitLeftRef.current,
      style: STYLE_URL,
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
    })
    const right = new maplibregl.Map({
      container: splitRightRef.current,
      style: STYLE_URL,
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
    })
    splitLeftMapRef.current = left
    splitRightMapRef.current = right
    left.addControl(new maplibregl.NavigationControl(), 'top-right')
    right.addControl(new maplibregl.NavigationControl(), 'top-right')

    let syncing = false
    const syncFrom = (source: maplibregl.Map, target: maplibregl.Map) => () => {
      if (syncing) return
      syncing = true
      target.jumpTo({ center: source.getCenter(), zoom: source.getZoom() })
      syncing = false
    }
    left.on('move', syncFrom(left, right))
    right.on('move', syncFrom(right, left))

    left.on('load', () => {
      api.currentStatus().then((rows) => addStatusLayer(left, 'split-current', rows)).catch(() => undefined)
    })
    right.on('load', () => {
      api
        .forecastStatus(forecastYear, forecastWeek)
        .then((rows) => addStatusLayer(right, 'split-forecast', rows))
        .catch(() => undefined)
    })

    return () => {
      left.remove()
      right.remove()
      splitLeftMapRef.current = null
      splitRightMapRef.current = null
    }
  }, [splitActive])

  // Refresh forecast layer when quarter/year changes
  useEffect(() => {
    const right = splitRightMapRef.current
    if (!splitActive || !right) return
    api
      .forecastStatus(forecastYear, forecastWeek)
      .then((rows) => addStatusLayer(right, 'split-forecast', rows))
      .catch(() => undefined)
  }, [forecastYear, forecastWeek, splitActive])

  // Drawing tool: wire click handlers on the active (non-split) map
  useEffect(() => {
    const map = mapRef.current
    if (!map || tool === 'none') return

    function handleClick(e: maplibregl.MapMouseEvent) {
      const coord: [number, number] = [e.lngLat.lng, e.lngLat.lat]

      if (tool === 'point') {
        finishAnnotation({ type: 'Point', coordinates: coord })
        return
      }
      if (tool === 'buffer') {
        const radiusStr = window.prompt('Buffer radius in meters?', '200')
        if (!radiusStr) return
        const radius = Number(radiusStr)
        if (!Number.isFinite(radius) || radius <= 0) return
        finishAnnotation(circlePolygon(coord, radius))
        return
      }
      // line / polygon: accumulate points
      setDraftPoints((prev) => [...prev, coord])
    }

    map.on('click', handleClick)
    return () => {
      map.off('click', handleClick)
    }
  }, [tool])

  // Render the in-progress sketch for line/polygon tools
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const sourceId = 'draft-sketch'
    const data: FeatureCollection = {
      type: 'FeatureCollection',
      features:
        draftPoints.length > 0
          ? [
              {
                type: 'Feature',
                geometry: tool === 'polygon' && draftPoints.length > 2
                  ? { type: 'Polygon', coordinates: [[...draftPoints, draftPoints[0]]] }
                  : { type: 'LineString', coordinates: draftPoints },
                properties: {},
              },
            ]
          : [],
    }
    const apply = () => {
      const existing = map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined
      if (existing) {
        existing.setData(data)
        return
      }
      if (!map.isStyleLoaded()) return
      map.addSource(sourceId, { type: 'geojson', data })
      map.addLayer({
        id: `${sourceId}-line`,
        type: 'line',
        source: sourceId,
        paint: { 'line-color': '#facc15', 'line-width': 2 },
      })
    }
    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)
  }, [draftPoints, tool])

  async function finishAnnotation(geometry: Geometry) {
    if (!selectedProjectId) {
      setStatus('Pick a note/project first')
      return
    }
    const label = window.prompt('Label for this annotation? (optional)') ?? undefined
    try {
      await api.addAnnotation(selectedProjectId, geometry as unknown as Record<string, unknown>, label || undefined)
      setStatus('Annotation added')
      setDraftPoints([])
      setTool('none')
    } catch (err) {
      setStatus(err instanceof ApiError ? err.message : 'Could not add annotation')
    }
  }

  function finishDraft() {
    if (tool === 'line' && draftPoints.length >= 2) {
      finishAnnotation({ type: 'LineString', coordinates: draftPoints })
    } else if (tool === 'polygon' && draftPoints.length >= 3) {
      finishAnnotation({ type: 'Polygon', coordinates: [[...draftPoints, draftPoints[0]]] })
    }
  }

  return (
    <div className="space-y-4">
      <GlassPanel className="flex flex-wrap items-end gap-3">
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/45">View</p>
          <button
            onClick={() => setSplitActive((v) => !v)}
            className={`rounded-xl px-4 py-2 text-sm font-semibold ${
              splitActive ? 'bg-gradient-to-r from-sky-400 to-sky-500 text-ink-900' : 'border border-white/20 text-white/80'
            }`}
          >
            {splitActive ? 'Split: Actual vs Forecast' : 'Single map'}
          </button>
        </div>

        {splitActive && (
          <>
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
                Forecast year
              </label>
              <input
                type="number"
                value={forecastYear}
                onChange={(e) => setForecastYear(Number(e.target.value))}
                className="w-24 rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm focus:border-sky-400/60 focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
                Quarter
              </label>
              <div className="flex gap-1">
                {QUARTER_WEEKS.map((w, i) => (
                  <button
                    key={w}
                    onClick={() => setForecastWeek(w)}
                    className={`rounded-lg px-2.5 py-2 text-xs font-semibold ${
                      forecastWeek === w ? 'bg-accent-400 text-ink-900' : 'border border-white/20 text-white/70'
                    }`}
                  >
                    Q{i + 1}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}

        {!splitActive && (
          <>
            <div className="min-w-[180px]">
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
                Note/project
              </label>
              <select
                value={selectedProjectId}
                onChange={(e) => setSelectedProjectId(e.target.value)}
                className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm focus:border-sky-400/60 focus:outline-none"
              >
                <option value="" className="bg-ink-900">
                  Select…
                </option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id} className="bg-ink-900">
                    {p.title}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/45">Draw</p>
              <div className="flex gap-1.5">
                {(['point', 'line', 'polygon', 'buffer'] as DrawTool[]).map((t) => (
                  <button
                    key={t}
                    onClick={() => {
                      setDraftPoints([])
                      setTool((cur) => (cur === t ? 'none' : t))
                    }}
                    className={`rounded-lg px-3 py-2 text-xs font-semibold capitalize ${
                      tool === t ? 'bg-sky-400 text-ink-900' : 'border border-white/20 text-white/70'
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
            {(tool === 'line' || tool === 'polygon') && (
              <button
                onClick={finishDraft}
                className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-ink-900"
              >
                Finish ({draftPoints.length} pts)
              </button>
            )}
          </>
        )}

        {status && <p className="text-sm text-white/70">{status}</p>}
      </GlassPanel>

      {!splitActive && (
        <div ref={containerRef} className="h-[70vh] w-full overflow-hidden rounded-3xl border border-white/15" />
      )}

      {splitActive && (
        <div className="grid h-[70vh] grid-cols-2 gap-2">
          <div className="relative overflow-hidden rounded-3xl border border-white/15">
            <div className="absolute left-2 top-2 z-10 rounded-lg bg-ink-900/80 px-2.5 py-1 text-xs font-semibold text-white/90">
              Current status
            </div>
            <div ref={splitLeftRef} className="h-full w-full" />
          </div>
          <div className="relative overflow-hidden rounded-3xl border border-white/15">
            <div className="absolute left-2 top-2 z-10 rounded-lg bg-ink-900/80 px-2.5 py-1 text-xs font-semibold text-white/90">
              Forecast
            </div>
            <div ref={splitRightRef} className="h-full w-full" />
          </div>
        </div>
      )}
    </div>
  )
}
