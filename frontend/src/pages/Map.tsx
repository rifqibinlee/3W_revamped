import type { Feature, FeatureCollection, Geometry, Polygon } from 'geojson'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState, type ReactElement } from 'react'
import { GlassPanel } from '../components/GlassPanel'
import {
  api,
  ApiError,
  type AnnotationOut,
  type CurrentStatusRow,
  type MapBounds,
  type MapStats,
  type OverviewStats,
  type SiteDetail,
  type UserOut,
} from '../lib/api'

const STYLE_URL = 'https://demotiles.maplibre.org/style.json'
// Centered on the real site distribution across Peninsular Malaysia
// (lat 1.3-6.2, lng 101.6-104.3), not just the Klang Valley — zoom 7
// keeps the whole network visible by default instead of an empty patch.
const DEFAULT_CENTER: [number, number] = [102.9, 3.15]
const DEFAULT_ZOOM = 7

type DrawTool = 'none' | 'point' | 'line' | 'polygon' | 'buffer'
type AnnotationMode = 'note' | 'project'

const QUARTER_WEEKS = [13, 26, 39, 52]

const DRAW_TOOLS: { tool: DrawTool; label: string; icon: ReactElement }[] = [
  {
    tool: 'point',
    label: 'Point',
    icon: (
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="4" fill="currentColor" />
      </svg>
    ),
  },
  {
    tool: 'line',
    label: 'Line',
    icon: (
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="5" cy="19" r="2" fill="currentColor" />
        <circle cx="19" cy="5" r="2" fill="currentColor" />
        <line x1="6.5" y1="17.5" x2="17.5" y2="6.5" />
      </svg>
    ),
  },
  {
    tool: 'polygon',
    label: 'Polygon',
    icon: (
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
        <polygon points="12,3 21,9 17,21 7,21 3,9" />
      </svg>
    ),
  },
  {
    tool: 'buffer',
    label: 'Buffer',
    icon: (
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="3" fill="currentColor" />
        <circle cx="12" cy="12" r="8" strokeDasharray="3 3" />
      </svg>
    ),
  },
]

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

const EARTH_RADIUS_M = 6371000

function haversineDistanceMeters([lng1, lat1]: [number, number], [lng2, lat2]: [number, number]): number {
  const toRad = (d: number) => (d * Math.PI) / 180
  const dLat = toRad(lat2 - lat1)
  const dLng = toRad(lng2 - lng1)
  const a =
    Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(a))
}

// Initial bearing along the great-circle path from point 1 to point 2,
// 0-360 degrees clockwise from true north.
function bearingDegrees([lng1, lat1]: [number, number], [lng2, lat2]: [number, number]): number {
  const toRad = (d: number) => (d * Math.PI) / 180
  const y = Math.sin(toRad(lng2 - lng1)) * Math.cos(toRad(lat2))
  const x =
    Math.cos(toRad(lat1)) * Math.sin(toRad(lat2)) -
    Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(toRad(lng2 - lng1))
  return (Math.atan2(y, x) * 180) / Math.PI < 0 ? (Math.atan2(y, x) * 180) / Math.PI + 360 : (Math.atan2(y, x) * 180) / Math.PI
}

function fmtDistance(meters: number): string {
  return meters >= 1000 ? `${(meters / 1000).toFixed(2)} km` : `${meters.toFixed(0)} m`
}

function fmt(n: number | null | undefined, digits = 1): string {
  return n == null || Number.isNaN(n) ? '—' : n.toFixed(digits)
}

function fmtCurrency(n: number | null | undefined): string {
  return n == null ? '—' : `RM ${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
}

function readBounds(map: maplibregl.Map): MapBounds {
  const b = map.getBounds()
  return { south: b.getSouth(), west: b.getWest(), north: b.getNorth(), east: b.getEast() }
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

// Two separate clustered sources (normal / congested) rather than one
// mixed source — matches the legacy app's two markerClusterGroup
// buckets (cluster-normal vs cluster-congested), so a cluster bubble's
// color is always unambiguous instead of needing a mixed-state color.
// maxClusterRadius:60 in the legacy Leaflet config maps directly to
// MapLibre's clusterRadius.
function addStatusLayer(map: maplibregl.Map, sourceId: string, rows: CurrentStatusRow[], onSiteClick?: (siteId: string) => void) {
  const normalGeojson = statusGeoJson(rows.filter((r) => !r.congested))
  const congestedGeojson = statusGeoJson(rows.filter((r) => r.congested))

  const normalId = `${sourceId}-normal`
  const congestedId = `${sourceId}-congested`

  const existing = map.getSource(normalId) as maplibregl.GeoJSONSource | undefined
  if (existing) {
    existing.setData(normalGeojson)
    ;(map.getSource(congestedId) as maplibregl.GeoJSONSource).setData(congestedGeojson)
    return
  }

  const buildBucket = (id: string, data: GeoJSON.FeatureCollection, color: string) => {
    map.addSource(id, { type: 'geojson', data, cluster: true, clusterMaxZoom: 14, clusterRadius: 60 })
    map.addLayer({
      id: `${id}-cluster-circle`,
      type: 'circle',
      source: id,
      filter: ['has', 'point_count'],
      paint: {
        'circle-radius': ['step', ['get', 'point_count'], 16, 25, 20, 100, 26],
        'circle-color': color,
        'circle-opacity': 0.85,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#ffffff',
      },
    })
    map.addLayer({
      id: `${id}-cluster-count`,
      type: 'symbol',
      source: id,
      filter: ['has', 'point_count'],
      layout: { 'text-field': '{point_count_abbreviated}', 'text-size': 12, 'text-font': ['Open Sans Bold'] },
      paint: { 'text-color': '#ffffff' },
    })
    map.addLayer({
      id: `${id}-point`,
      type: 'circle',
      source: id,
      filter: ['!', ['has', 'point_count']],
      paint: {
        'circle-radius': 6,
        'circle-color': color,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#ffffff',
      },
    })

    map.on('mouseenter', `${id}-cluster-circle`, () => (map.getCanvas().style.cursor = 'pointer'))
    map.on('mouseleave', `${id}-cluster-circle`, () => (map.getCanvas().style.cursor = ''))
    map.on('mouseenter', `${id}-point`, () => (map.getCanvas().style.cursor = 'pointer'))
    map.on('mouseleave', `${id}-point`, () => (map.getCanvas().style.cursor = ''))

    map.on('click', `${id}-cluster-circle`, (e) => {
      const f = e.features?.[0]
      if (!f) return
      const clusterId = (f.properties as { cluster_id: number }).cluster_id
      const source = map.getSource(id) as maplibregl.GeoJSONSource
      source.getClusterExpansionZoom(clusterId).then((zoom) => {
        map.easeTo({ center: (f.geometry as GeoJSON.Point).coordinates as [number, number], zoom })
      })
    })

    map.on('click', `${id}-point`, (e) => {
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

  buildBucket(normalId, normalGeojson, '#3b82f6')
  buildBucket(congestedId, congestedGeojson, '#dc2626')
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

function MapStatsPanel({ title, stats }: { title: string; stats: MapStats | null }) {
  return (
    <GlassPanel>
      <p className="mb-3.5 font-display text-sm font-semibold">{title}</p>
      {!stats ? (
        <p className="text-sm text-white/50">Pan or zoom the map to see stats for this area.</p>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-white/45">Sites</p>
            <p className="font-display text-lg font-semibold">{stats.total_sites}</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-white/45">Congested</p>
            <p className="font-display text-lg font-semibold text-red-300">{stats.congested_sites}</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-white/45">Healthy</p>
            <p className="font-display text-lg font-semibold text-green-300">{stats.healthy_sites}</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-white/45">Coverage holes</p>
            <p className="font-display text-lg font-semibold">{stats.coverage_holes}</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-white/45">CAPEX needed</p>
            <p className="font-display text-lg font-semibold">{fmtCurrency(stats.total_capex)}</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-white/45">Worst coverage hole</p>
            <p className="text-sm font-semibold">
              {stats.worst_coverage_hole
                ? `#${stats.worst_coverage_hole.cluster_id} (${stats.worst_coverage_hole.data_source}) · ${stats.worst_coverage_hole.point_count} pts`
                : '—'}
            </p>
          </div>
        </div>
      )}
    </GlassPanel>
  )
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

  const [users, setUsers] = useState<UserOut[]>([])
  const [overview, setOverview] = useState<OverviewStats | null>(null)
  const [mapBounds, setMapBounds] = useState<MapBounds | null>(null)
  const [currentStats, setCurrentStats] = useState<MapStats | null>(null)
  const [forecastStats, setForecastStats] = useState<MapStats | null>(null)
  const [tool, setTool] = useState<DrawTool>('none')
  const [drawMenuOpen, setDrawMenuOpen] = useState(false)
  const [measureActive, setMeasureActive] = useState(false)
  const [measurePoints, setMeasurePoints] = useState<[number, number][]>([])
  const [draftPoints, setDraftPoints] = useState<[number, number][]>([])
  const [status, setStatus] = useState<string | null>(null)

  // In-app dialog replacing window.prompt — buffer needs a radius before the
  // geometry even exists; once geometry is ready, drawing creates a brand
  // new note or project right there (toggle between the two), not an
  // annotation under some pre-existing project.
  const [pendingBufferCenter, setPendingBufferCenter] = useState<[number, number] | null>(null)
  const [pendingGeometry, setPendingGeometry] = useState<Geometry | null>(null)
  const [annotationMode, setAnnotationMode] = useState<AnnotationMode>('note')
  const [titleInput, setTitleInput] = useState('')
  const [descriptionInput, setDescriptionInput] = useState('')
  const [assigneeIdInput, setAssigneeIdInput] = useState('')
  const [radiusInput, setRadiusInput] = useState('200')

  useEffect(() => {
    api.listUsers().then(setUsers).catch(() => undefined)
  }, [])

  useEffect(() => {
    api.overviewStats().then(setOverview).catch(() => undefined)
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
      setMapBounds(readBounds(map))
    })
    map.on('moveend', () => setMapBounds(readBounds(map)))

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
    left.on('moveend', () => setMapBounds(readBounds(left)))

    left.on('load', () => {
      api.currentStatus().then((rows) => addStatusLayer(left, 'split-current', rows)).catch(() => undefined)
      setMapBounds(readBounds(left))
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

  // Bounds-scoped current stats, for the tab beneath the map
  useEffect(() => {
    if (!mapBounds) return
    api.mapStats(mapBounds).then(setCurrentStats).catch(() => setCurrentStats(null))
  }, [mapBounds])

  // Forecast stats for the same bounds — only relevant in split mode
  useEffect(() => {
    if (!mapBounds || !splitActive) return
    api
      .mapStats(mapBounds, forecastYear, forecastWeek)
      .then(setForecastStats)
      .catch(() => setForecastStats(null))
  }, [mapBounds, splitActive, forecastYear, forecastWeek])

  // Render newly created annotations as they're saved, accumulating across
  // the session so the map fills up as the user keeps drawing
  const [createdAnnotations, setCreatedAnnotations] = useState<AnnotationOut[]>([])
  useEffect(() => {
    const map = mapRef.current
    if (!map || splitActive) return
    addAnnotationsLayer(map, createdAnnotations)
  }, [createdAnnotations, splitActive])

  // Drawing tool: wire click handlers on the active (non-split) map
  useEffect(() => {
    const map = mapRef.current
    if (!map || tool === 'none') return

    function handleClick(e: maplibregl.MapMouseEvent) {
      const coord: [number, number] = [e.lngLat.lng, e.lngLat.lat]

      if (tool === 'point') {
        resetDialogFields()
        setPendingGeometry({ type: 'Point', coordinates: coord })
        return
      }
      if (tool === 'buffer') {
        resetDialogFields()
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

  // Measurement tool: independent of the draw tool, doesn't create
  // annotations — just accumulates clicked points to report distance
  // and bearing between them.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !measureActive) return
    function handleClick(e: maplibregl.MapMouseEvent) {
      setMeasurePoints((prev) => [...prev, [e.lngLat.lng, e.lngLat.lat]])
    }
    map.on('click', handleClick)
    return () => {
      map.off('click', handleClick)
    }
  }, [measureActive])

  // Render the measurement line + per-segment distance/bearing labels
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const sourceId = 'measure-line'
    const pointSourceId = 'measure-points'
    const labelSourceId = 'measure-labels'

    const lineData: FeatureCollection = {
      type: 'FeatureCollection',
      features: measurePoints.length >= 2 ? [{ type: 'Feature', geometry: { type: 'LineString', coordinates: measurePoints }, properties: {} }] : [],
    }
    const pointData: FeatureCollection = {
      type: 'FeatureCollection',
      features: measurePoints.map((p) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: p }, properties: {} })),
    }
    const labelData: FeatureCollection = {
      type: 'FeatureCollection',
      features: measurePoints.slice(1).map((p, i) => {
        const prev = measurePoints[i]
        const mid: [number, number] = [(prev[0] + p[0]) / 2, (prev[1] + p[1]) / 2]
        const dist = haversineDistanceMeters(prev, p)
        const bearing = bearingDegrees(prev, p)
        return { type: 'Feature', geometry: { type: 'Point', coordinates: mid }, properties: { label: `${fmtDistance(dist)} · ${bearing.toFixed(0)}°` } }
      }),
    }

    const apply = () => {
      const existingLine = map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined
      if (existingLine) {
        existingLine.setData(lineData)
        ;(map.getSource(pointSourceId) as maplibregl.GeoJSONSource).setData(pointData)
        ;(map.getSource(labelSourceId) as maplibregl.GeoJSONSource).setData(labelData)
        return
      }
      if (!map.isStyleLoaded()) return
      map.addSource(sourceId, { type: 'geojson', data: lineData })
      map.addLayer({ id: `${sourceId}-line`, type: 'line', source: sourceId, paint: { 'line-color': '#22d3ee', 'line-width': 2, 'line-dasharray': [2, 1] } })
      map.addSource(pointSourceId, { type: 'geojson', data: pointData })
      map.addLayer({
        id: `${pointSourceId}-circle`,
        type: 'circle',
        source: pointSourceId,
        paint: { 'circle-radius': 5, 'circle-color': '#22d3ee', 'circle-stroke-width': 2, 'circle-stroke-color': '#ffffff' },
      })
      map.addSource(labelSourceId, { type: 'geojson', data: labelData })
      map.addLayer({
        id: `${labelSourceId}-symbol`,
        type: 'symbol',
        source: labelSourceId,
        layout: { 'text-field': ['get', 'label'], 'text-size': 11, 'text-offset': [0, -1] },
        paint: { 'text-color': '#22d3ee', 'text-halo-color': '#0b1220', 'text-halo-width': 1.5 },
      })
    }
    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)
  }, [measurePoints])

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

  function resetDialogFields() {
    setAnnotationMode('note')
    setTitleInput('')
    setDescriptionInput('')
    setAssigneeIdInput('')
    setRadiusInput('200')
  }

  async function createNoteOrProjectWithAnnotation(geometry: Geometry) {
    if (!titleInput.trim()) {
      setStatus('Title is required')
      return
    }
    if (annotationMode === 'project' && !assigneeIdInput) {
      setStatus('Pick an assignee for the project')
      return
    }
    try {
      const project = await api.createProject({
        title: titleInput.trim(),
        description: descriptionInput.trim() || undefined,
        assignee_id: annotationMode === 'project' ? assigneeIdInput : undefined,
      })
      const annotation = await api.addAnnotation(project.id, geometry as unknown as Record<string, unknown>, titleInput.trim())
      setCreatedAnnotations((prev) => [...prev, annotation])
      setStatus(`${annotationMode === 'project' ? 'Project' : 'Note'} created`)
      setDraftPoints([])
      setTool('none')
    } catch (err) {
      setStatus(err instanceof ApiError ? err.message : 'Could not create annotation')
    }
  }

  function finishDraft() {
    resetDialogFields()
    if (tool === 'line' && draftPoints.length >= 2) {
      setPendingGeometry({ type: 'LineString', coordinates: draftPoints })
    } else if (tool === 'polygon' && draftPoints.length >= 3) {
      setPendingGeometry({ type: 'Polygon', coordinates: [[...draftPoints, draftPoints[0]]] })
    }
  }

  function confirmGeometryDialog() {
    if (pendingGeometry) {
      createNoteOrProjectWithAnnotation(pendingGeometry)
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
    createNoteOrProjectWithAnnotation(circlePolygon(pendingBufferCenter, radius))
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
            <div className="relative">
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/45">Draw</p>
              <button
                onClick={() => setDrawMenuOpen((v) => !v)}
                title="Draw an annotation"
                className={`flex h-9 w-9 items-center justify-center rounded-xl ${
                  tool !== 'none' ? 'bg-sky-400 text-ink-900' : 'border border-white/20 text-white/80'
                }`}
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 5v14M5 12h14" />
                </svg>
              </button>

              {drawMenuOpen && (
                <div className="absolute left-0 top-full z-20 mt-2 flex gap-1.5 rounded-2xl border border-white/15 bg-ink-900/95 p-2 backdrop-blur-xl">
                  {DRAW_TOOLS.map(({ tool: t, label, icon }) => (
                    <button
                      key={t}
                      title={label}
                      onClick={() => {
                        setDraftPoints([])
                        setTool(t)
                        setDrawMenuOpen(false)
                        setMeasureActive(false)
                        setMeasurePoints([])
                      }}
                      className={`flex h-9 w-9 items-center justify-center rounded-xl ${
                        tool === t ? 'bg-sky-400 text-ink-900' : 'text-white/80 hover:bg-white/10'
                      }`}
                    >
                      {icon}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {tool !== 'none' && (
              <button
                onClick={() => {
                  setTool('none')
                  setDraftPoints([])
                }}
                className="rounded-xl border border-white/20 px-3 py-2 text-xs font-semibold text-white/70"
              >
                Cancel draw
              </button>
            )}

            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/45">Measure</p>
              <button
                onClick={() => {
                  if (!measureActive) {
                    setTool('none')
                    setDraftPoints([])
                  }
                  setMeasureActive((v) => !v)
                  setMeasurePoints([])
                }}
                title="Measure distance and bearing"
                className={`flex h-9 w-9 items-center justify-center rounded-xl ${
                  measureActive ? 'bg-sky-400 text-ink-900' : 'border border-white/20 text-white/80'
                }`}
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 17 17 3M5 19l2-2M9 15l2-2M13 11l2-2" />
                  <path d="M17 3l4 4-14 14-4-4z" />
                </svg>
              </button>
            </div>
            {measureActive && (
              <button
                onClick={() => setMeasurePoints([])}
                className="rounded-xl border border-white/20 px-3 py-2 text-xs font-semibold text-white/70"
              >
                Clear points
              </button>
            )}
            {measurePoints.length >= 2 && (
              <div className="rounded-xl border border-sky-400/30 bg-sky-400/10 px-3 py-2 text-xs">
                <span className="text-white/55">Total distance </span>
                <span className="font-semibold text-sky-300">
                  {fmtDistance(measurePoints.slice(1).reduce((sum, p, i) => sum + haversineDistanceMeters(measurePoints[i], p), 0))}
                </span>
              </div>
            )}
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

      <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
        {!splitActive && (
          <div ref={containerRef} className="h-[55vh] w-full overflow-hidden rounded-3xl border border-white/15" />
        )}

        {splitActive && (
          <div className="grid h-[55vh] grid-cols-2 gap-2">
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

        <GlassPanel>
          <p className="mb-3.5 font-display text-sm font-semibold">Network overview</p>
          <div className="space-y-2.5 text-sm">
            <div className="flex justify-between">
              <span className="text-white/55">Total sites</span>
              <span className="font-semibold">{overview?.total_sites ?? '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/55">Congested sites</span>
              <span className="font-semibold text-red-300">{overview?.total_congested_sites ?? '—'}</span>
            </div>
            <div>
              <p className="text-white/55">Total CAPEX needed</p>
              <p className="font-semibold">{fmtCurrency(overview?.total_capex)}</p>
            </div>
            <div className="border-t border-white/10 pt-2.5">
              <p className="text-white/55">Worst congested sector</p>
              <p className="font-semibold">
                {overview?.worst_congested_sector
                  ? `${overview.worst_congested_sector.zoom_sector_id} (${overview.worst_congested_sector.region}) · ${overview.worst_congested_sector.congested_weeks} wks`
                  : '—'}
              </p>
            </div>
            <div>
              <p className="text-white/55">Worst Ookla cluster</p>
              <p className="font-semibold">
                {overview?.worst_ookla_cluster
                  ? `#${overview.worst_ookla_cluster.cluster_id} · ${overview.worst_ookla_cluster.point_count} pts · ${fmt(overview.worst_ookla_cluster.avg_signal)} dBm`
                  : '—'}
              </p>
            </div>
            <div>
              <p className="text-white/55">Worst MR cluster</p>
              <p className="font-semibold">
                {overview?.worst_mr_cluster
                  ? `#${overview.worst_mr_cluster.cluster_id} · ${overview.worst_mr_cluster.point_count} pts · ${fmt(overview.worst_mr_cluster.avg_signal)} dBm`
                  : '—'}
              </p>
            </div>
          </div>
        </GlassPanel>
      </div>

      {!splitActive && <MapStatsPanel title="Viewport stats" stats={currentStats} />}

      {splitActive && (
        <div className="grid gap-4 md:grid-cols-2">
          <MapStatsPanel title="Viewport stats — current" stats={currentStats} />
          <MapStatsPanel title="Viewport stats — forecast" stats={forecastStats} />
        </div>
      )}

      {(pendingGeometry || pendingBufferCenter) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/60 backdrop-blur-sm">
          <GlassPanel className="w-full max-w-sm">
            <p className="mb-3.5 font-display text-sm font-semibold">
              {pendingBufferCenter ? 'New buffer annotation' : 'New annotation'}
            </p>

            <div className="mb-3 flex gap-1.5">
              <button
                onClick={() => setAnnotationMode('note')}
                className={`flex-1 rounded-xl px-3 py-2 text-xs font-semibold ${
                  annotationMode === 'note' ? 'bg-sky-400 text-ink-900' : 'border border-white/20 text-white/70'
                }`}
              >
                Note
              </button>
              <button
                onClick={() => setAnnotationMode('project')}
                className={`flex-1 rounded-xl px-3 py-2 text-xs font-semibold ${
                  annotationMode === 'project' ? 'bg-sky-400 text-ink-900' : 'border border-white/20 text-white/70'
                }`}
              >
                Project
              </button>
            </div>

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

            <div className="mb-3">
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">Title</label>
              <input
                type="text"
                autoFocus={!pendingBufferCenter}
                value={titleInput}
                onChange={(e) => setTitleInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Escape' && cancelDialog()}
                placeholder="e.g. New antenna pole"
                className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
              />
            </div>

            {annotationMode === 'project' && (
              <div className="mb-3">
                <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
                  Assignee
                </label>
                <select
                  value={assigneeIdInput}
                  onChange={(e) => setAssigneeIdInput(e.target.value)}
                  className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm focus:border-sky-400/60 focus:outline-none"
                >
                  <option value="" className="bg-ink-900">
                    Select…
                  </option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id} className="bg-ink-900">
                      {u.username}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
                Description
              </label>
              <textarea
                value={descriptionInput}
                onChange={(e) => setDescriptionInput(e.target.value)}
                rows={3}
                placeholder={annotationMode === 'project' ? 'Project description' : 'Note description'}
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
                onClick={pendingBufferCenter ? confirmBufferDialog : confirmGeometryDialog}
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
