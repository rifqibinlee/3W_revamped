import type { Feature, FeatureCollection, Geometry, Polygon } from 'geojson'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState } from 'react'
import { GlassPanel } from '../components/GlassPanel'
import { api, ApiError, type AnnotationOut, type CurrentStatusRow, type ProjectOut, type SiteDetail } from '../lib/api'

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

function fmt(n: number | null | undefined, digits = 1): string {
  return n == null || Number.isNaN(n) ? '—' : n.toFixed(digits)
}

function siteDetailHtml(siteId: string, detail: SiteDetail | null, loading: boolean): string {
  if (loading) {
    return `<div style="font-family:inherit;min-width:220px;padding:4px;"><strong>${siteId}</strong><br/><span style="opacity:.7">Loading…</span></div>`
  }
  if (!detail) {
    return `<div style="font-family:inherit;min-width:220px;padding:4px;"><strong>${siteId}</strong><br/><span style="opacity:.7">No data</span></div>`
  }

  const latest = detail.sectors[0]
  const statusLine = detail.congested
    ? '<span style="color:#f87171;font-weight:700;">⚠ Congested</span>'
    : '<span style="color:#4ade80;font-weight:700;">✓ Healthy</span>'

  const paramsHtml = latest
    ? `
      <table style="width:100%;font-size:11px;margin-top:6px;border-collapse:collapse;">
        <tr><td style="opacity:.6;padding:1px 0;">Data volume (GB)</td><td style="text-align:right;">${fmt(latest.eric_data_volume_ul_dl)}</td></tr>
        <tr><td style="opacity:.6;padding:1px 0;">PRB utilization</td><td style="text-align:right;">${fmt(latest.eric_prb_util_rate)}%</td></tr>
        <tr><td style="opacity:.6;padding:1px 0;">DL throughput</td><td style="text-align:right;">${fmt(latest.eric_dl_user_ip_thpt)}</td></tr>
        <tr><td style="opacity:.6;padding:1px 0;">Max RRC users</td><td style="text-align:right;">${fmt(latest.eric_max_rrc_user, 0)}</td></tr>
      </table>`
    : '<p style="font-size:11px;opacity:.6;margin-top:4px;">No sector KPIs available</p>'

  const nextForecast = detail.forecast[0]
  const forecastHtml = nextForecast
    ? `<p style="font-size:11px;margin-top:6px;"><strong>Forecast</strong> (Wk ${nextForecast.week}/${nextForecast.year}): ${nextForecast.congested ? '⚠ Congested' : '✓ Normal'} · ${fmt(nextForecast.predicted_eric_prb_util_rate)}% PRB</p>`
    : '<p style="font-size:11px;opacity:.6;margin-top:6px;">No forecast available</p>'

  const upgrade = detail.capex_upgrades[0] as Record<string, unknown> | undefined
  const capexHtml = upgrade
    ? `<p style="font-size:11px;margin-top:6px;"><strong>Upgrade:</strong> ${upgrade.suggested_upgrade_case ?? '—'}<br/>Est. CAPEX: RM ${fmt(upgrade.estimated_total_capex_rm as number, 0)}</p>`
    : '<p style="font-size:11px;opacity:.6;margin-top:6px;">No upgrade recommended</p>'

  return `
    <div style="font-family:inherit;min-width:220px;padding:4px;">
      <strong>${siteId}</strong> ${detail.site ? `· ${detail.site.region}` : ''}<br/>
      ${statusLine}
      ${paramsHtml}
      ${forecastHtml}
      ${capexHtml}
    </div>`
}

function addStatusLayer(map: maplibregl.Map, sourceId: string, rows: CurrentStatusRow[], onSiteClick?: (siteId: string) => void) {
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
  map.on('mouseenter', `${sourceId}-circle`, () => {
    map.getCanvas().style.cursor = 'pointer'
  })
  map.on('mouseleave', `${sourceId}-circle`, () => {
    map.getCanvas().style.cursor = ''
  })
  map.on('click', `${sourceId}-circle`, (e) => {
    const f = e.features?.[0]
    if (!f) return
    const props = f.properties as { site_id: string }
    const popup = new maplibregl.Popup().setLngLat(e.lngLat).setHTML(siteDetailHtml(props.site_id, null, true)).addTo(map)
    api
      .siteDetail(props.site_id)
      .then((detail) => popup.setHTML(siteDetailHtml(props.site_id, detail, false)))
      .catch(() => popup.setHTML(siteDetailHtml(props.site_id, null, false)))
    onSiteClick?.(props.site_id)
  })
}

function annotationToFeature(a: AnnotationOut): Feature {
  return { type: 'Feature', geometry: a.geometry as unknown as Geometry, properties: { label: a.label ?? '' } }
}

function clickPopup(map: maplibregl.Map, layerId: string) {
  map.on('click', layerId, (e) => {
    const f = e.features?.[0]
    if (!f) return
    const label = (f.properties as { label: string }).label
    new maplibregl.Popup().setLngLat(e.lngLat).setHTML(`<strong>${label || 'Annotation'}</strong>`).addTo(map)
  })
}

function setSourceData(map: maplibregl.Map, sourceId: string, features: Feature[]): boolean {
  const data: FeatureCollection = { type: 'FeatureCollection', features }
  const existing = map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined
  if (existing) {
    existing.setData(data)
    return true
  }
  map.addSource(sourceId, { type: 'geojson', data })
  return false
}

function addAnnotationsLayer(map: maplibregl.Map, annotations: AnnotationOut[]) {
  if (!map.isStyleLoaded()) {
    map.once('load', () => addAnnotationsLayer(map, annotations))
    return
  }

  const features = annotations.map(annotationToFeature)
  const pointFeatures = features.filter((f) => f.geometry.type === 'Point')
  const lineFeatures = features.filter((f) => f.geometry.type === 'LineString')
  const polygonFeatures = features.filter((f) => f.geometry.type === 'Polygon')

  if (!setSourceData(map, 'annotation-points', pointFeatures)) {
    map.addLayer({
      id: 'annotation-points-layer',
      type: 'circle',
      source: 'annotation-points',
      paint: { 'circle-radius': 7, 'circle-color': '#facc15', 'circle-stroke-width': 2, 'circle-stroke-color': '#1e1b4b' },
    })
    clickPopup(map, 'annotation-points-layer')
  }

  if (!setSourceData(map, 'annotation-lines', lineFeatures)) {
    map.addLayer({
      id: 'annotation-lines-layer',
      type: 'line',
      source: 'annotation-lines',
      paint: { 'line-color': '#facc15', 'line-width': 2 },
    })
    clickPopup(map, 'annotation-lines-layer')
  }

  if (!setSourceData(map, 'annotation-polygons', polygonFeatures)) {
    map.addLayer({
      id: 'annotation-polygons-fill',
      type: 'fill',
      source: 'annotation-polygons',
      paint: { 'fill-color': '#facc15', 'fill-opacity': 0.15 },
    })
    map.addLayer({
      id: 'annotation-polygons-line',
      type: 'line',
      source: 'annotation-polygons',
      paint: { 'line-color': '#facc15', 'line-width': 2 },
    })
    clickPopup(map, 'annotation-polygons-fill')
  }
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
  const [annotationsVersion, setAnnotationsVersion] = useState(0)

  // In-app dialogs replacing window.prompt — buffer needs a radius before
  // the geometry even exists, point/line/polygon just need a label.
  const [pendingBufferCenter, setPendingBufferCenter] = useState<[number, number] | null>(null)
  const [pendingGeometry, setPendingGeometry] = useState<Geometry | null>(null)
  const [labelInput, setLabelInput] = useState('')
  const [radiusInput, setRadiusInput] = useState('200')

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

  // Render the selected project's saved annotations, reloading whenever the
  // project changes or a new one is added
  useEffect(() => {
    const map = mapRef.current
    if (!map || splitActive || !selectedProjectId) return
    api
      .listAnnotations(selectedProjectId)
      .then((rows) => addAnnotationsLayer(map, rows))
      .catch(() => undefined)
  }, [selectedProjectId, annotationsVersion, splitActive])

  // Drawing tool: wire click handlers on the active (non-split) map
  useEffect(() => {
    const map = mapRef.current
    if (!map || tool === 'none') return

    function handleClick(e: maplibregl.MapMouseEvent) {
      const coord: [number, number] = [e.lngLat.lng, e.lngLat.lat]

      if (tool === 'point') {
        setLabelInput('')
        setPendingGeometry({ type: 'Point', coordinates: coord })
        return
      }
      if (tool === 'buffer') {
        setLabelInput('')
        setRadiusInput('200')
        setPendingBufferCenter(coord)
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

  async function finishAnnotation(geometry: Geometry, label: string) {
    if (!selectedProjectId) {
      setStatus('Pick a note/project first')
      return
    }
    try {
      await api.addAnnotation(selectedProjectId, geometry as unknown as Record<string, unknown>, label || undefined)
      setStatus('Annotation added')
      setAnnotationsVersion((v) => v + 1)
      setDraftPoints([])
      setTool('none')
    } catch (err) {
      setStatus(err instanceof ApiError ? err.message : 'Could not add annotation')
    }
  }

  function finishDraft() {
    setLabelInput('')
    if (tool === 'line' && draftPoints.length >= 2) {
      setPendingGeometry({ type: 'LineString', coordinates: draftPoints })
    } else if (tool === 'polygon' && draftPoints.length >= 3) {
      setPendingGeometry({ type: 'Polygon', coordinates: [[...draftPoints, draftPoints[0]]] })
    }
  }

  function confirmLabelDialog() {
    if (pendingGeometry) {
      finishAnnotation(pendingGeometry, labelInput.trim())
      setPendingGeometry(null)
    }
  }

  function confirmBufferDialog() {
    if (!pendingBufferCenter) return
    const radius = Number(radiusInput)
    if (!Number.isFinite(radius) || radius <= 0) {
      setStatus('Enter a valid radius in meters')
      return
    }
    finishAnnotation(circlePolygon(pendingBufferCenter, radius), labelInput.trim())
    setPendingBufferCenter(null)
  }

  function cancelDialog() {
    setPendingGeometry(null)
    setPendingBufferCenter(null)
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

      {(pendingGeometry || pendingBufferCenter) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/60 backdrop-blur-sm">
          <GlassPanel className="w-full max-w-sm">
            <p className="mb-3.5 font-display text-sm font-semibold">
              {pendingBufferCenter ? 'Buffer annotation' : 'Label this annotation'}
            </p>

            {pendingBufferCenter && (
              <div className="mb-3">
                <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
                  Radius (meters)
                </label>
                <input
                  type="number"
                  autoFocus
                  value={radiusInput}
                  onChange={(e) => setRadiusInput(e.target.value)}
                  className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm focus:border-sky-400/60 focus:outline-none"
                />
              </div>
            )}

            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
                Label (optional)
              </label>
              <input
                type="text"
                autoFocus={!pendingBufferCenter}
                value={labelInput}
                onChange={(e) => setLabelInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    if (pendingBufferCenter) confirmBufferDialog()
                    else confirmLabelDialog()
                  }
                  if (e.key === 'Escape') cancelDialog()
                }}
                placeholder="e.g. New antenna pole"
                className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
              />
            </div>

            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={cancelDialog}
                className="rounded-xl border border-white/20 px-4 py-2 text-sm font-semibold text-white/75"
              >
                Cancel
              </button>
              <button
                onClick={pendingBufferCenter ? confirmBufferDialog : confirmLabelDialog}
                className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-ink-900"
              >
                Save
              </button>
            </div>
          </GlassPanel>
        </div>
      )}
    </div>
  )
}
