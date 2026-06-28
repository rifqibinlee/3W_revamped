import type { Feature, FeatureCollection, Geometry, Polygon } from 'geojson'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState, type ReactElement } from 'react'
import { GlassPanel } from '../components/GlassPanel'
import {
  api,
  ApiError,
  type AnnotationOut,
  type CctvRunResult,
  type CoverageHolePoint,
  type CurrentStatusRow,
  type GensetRouteResult,
  type GeoserverLayer,
  type MapBounds,
  type MapStats,
  type OverviewStats,
  type SiteCoverageRow,
  type UserOut,
} from '../lib/api'
import { addStatusLayer, fmt, getBaseStyle, statusGeoJson } from '../lib/mapLayers'
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
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="4" fill="currentColor" />
      </svg>
    ),
  },
  {
    tool: 'line',
    label: 'Line',
    icon: (
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
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
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="12,3 21,9 17,21 7,21 3,9" />
      </svg>
    ),
  },
  {
    tool: 'buffer',
    label: 'Buffer',
    icon: (
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3" fill="currentColor" />
        <circle cx="12" cy="12" r="8" strokeDasharray="3 3" />
      </svg>
    ),
  },
]

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

const TECH_COLORS: Record<string, string> = { '5G': '#eab308', '4G': '#3b82f6', '3G': '#f97316', '2G': '#6b7280' }

// A 65° sector wedge centered on the cell's azimuth — the antenna's
// real horizontal beamwidth varies by hardware and isn't in
// site_coverage_params, so this is a representative approximation
// (a common macro-sector beamwidth) rather than an exact pattern,
// same simplification the legacy app's client-side annulus-sector
// drawing made.
function sectorWedgePolygon(center: [number, number], radiusMeters: number, azimuthDeg: number, beamwidthDeg = 65): Polygon {
  const segments = 24
  const [lng, lat] = center
  const latRad = (lat * Math.PI) / 180
  const metersPerDegLat = 111320
  const metersPerDegLng = 111320 * Math.cos(latRad)
  const startDeg = azimuthDeg - beamwidthDeg / 2
  const coords: [number, number][] = [[lng, lat]]
  for (let i = 0; i <= segments; i++) {
    const bearing = ((startDeg + (i / segments) * beamwidthDeg) * Math.PI) / 180
    coords.push([
      lng + (radiusMeters * Math.sin(bearing)) / metersPerDegLng,
      lat + (radiusMeters * Math.cos(bearing)) / metersPerDegLat,
    ])
  }
  coords.push([lng, lat])
  return { type: 'Polygon', coordinates: [coords] }
}

function fmtCurrency(n: number | null | undefined): string {
  return n == null ? '—' : `RM ${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
}

function readBounds(map: maplibregl.Map): MapBounds {
  const b = map.getBounds()
  return { south: b.getSouth(), west: b.getWest(), north: b.getNorth(), east: b.getEast() }
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
  const [currentStatusRows, setCurrentStatusRows] = useState<CurrentStatusRow[]>([])
  const [forecastStats, setForecastStats] = useState<MapStats | null>(null)
  const [tool, setTool] = useState<DrawTool>('none')
  const [drawMenuOpen, setDrawMenuOpen] = useState(false)
  const [measureActive, setMeasureActive] = useState(false)
  const [measurePoints, setMeasurePoints] = useState<[number, number][]>([])
  const baseLayerIdsRef = useRef<string[]>([])

  const [layersOpen, setLayersOpen] = useState(false)
  const [legendsOpen, setLegendsOpen] = useState(true)

  const LAYER_LEGEND_ITEMS = [
    ['healthySites', 'Healthy sites', <span key="sw" className="h-2.5 w-2.5 rounded-full bg-[#3b82f6]" />],
    ['congestedSites', 'Congested sites', <span key="sw" className="h-2.5 w-2.5 rounded-full bg-[#dc2626]" />],
    ['heatmap', 'Heatmap (congested)', <span key="sw" className="h-2.5 w-5 rounded-sm" style={{ background: 'linear-gradient(90deg,#1d4ed8,#22d3ee,#facc15,#fb923c,#dc2626)' }} />],
    ['coverage5g', '5G coverage', <span key="sw" className="h-2.5 w-2.5 rounded-full" style={{ background: TECH_COLORS['5G'] }} />],
    ['coverage4g', '4G coverage', <span key="sw" className="h-2.5 w-2.5 rounded-full" style={{ background: TECH_COLORS['4G'] }} />],
    ['coverage3g', '3G coverage', <span key="sw" className="h-2.5 w-2.5 rounded-full" style={{ background: TECH_COLORS['3G'] }} />],
    ['coverage2g', '2G coverage', <span key="sw" className="h-2.5 w-2.5 rounded-full" style={{ background: TECH_COLORS['2G'] }} />],
    ['signalHigh', 'Signal (-100 to -120)', <span key="sw" className="h-2.5 w-2.5 rounded-full bg-[#facc15]" />],
    ['signalMid', 'Signal (-121 to -130)', <span key="sw" className="h-2.5 w-2.5 rounded-full bg-[#f97316]" />],
    ['signalLow', 'Signal (<-130)', <span key="sw" className="h-2.5 w-2.5 rounded-full bg-[#dc2626]" />],
  ] as const
  const [baseMap, setBaseMap] = useState<'normal' | 'satellite'>('satellite')
  const [layerToggles, setLayerToggles] = useState({
    healthySites: true, congestedSites: true, heatmap: false,
    coverage2g: false, coverage3g: false, coverage4g: false, coverage5g: false,
    signalHigh: false, signalMid: false, signalLow: false,
  })
  const [geoserverLayerList, setGeoserverLayerList] = useState<GeoserverLayer[]>([])
  const [activeGeoserverLayers, setActiveGeoserverLayers] = useState<Set<string>>(new Set())

  // Fixed layer names the Genset/Bitcoin-mining tools always query —
  // not user-selectable (see backend Settings.geoserver_substations_layer
  // / geoserver_buildings_layer).
  const [fixedLayers, setFixedLayers] = useState<{ substations_layer: string; buildings_layer: string } | null>(null)

  // Genset-single and the power-draw check are inline panels anchored to
  // the far right of the toolbar (so the map stays visible to click a
  // site while the panel is open) rather than a centered modal —
  // genset-bulk and CCTV stay modals since they're file-upload forms
  // that don't need the map visible while filling them in.
  const [activeToolPanel, setActiveToolPanel] = useState<'none' | 'genset-bulk' | 'cctv'>('none')
  const [rightPanel, setRightPanel] = useState<'none' | 'genset-single' | 'bitcoin'>('none')

  const [gensetMenuOpen, setGensetMenuOpen] = useState(false)
  const [gensetSiteId, setGensetSiteId] = useState('')
  const [gensetPickMode, setGensetPickMode] = useState(false)
  const [gensetPickedLatLng, setGensetPickedLatLng] = useState<[number, number] | null>(null)
  const [gensetBulkFile, setGensetBulkFile] = useState<File | null>(null)
  const [gensetStatus, setGensetStatus] = useState<string | null>(null)
  const [gensetResult, setGensetResult] = useState<GensetRouteResult | null>(null)
  const [gensetBulkResults, setGensetBulkResults] = useState<{ siteId: string; result: GensetRouteResult | null; error: string | null }[]>([])

  const [cctvBuildingFile, setCctvBuildingFile] = useState<File | null>(null)
  const [cctvParkingFile, setCctvParkingFile] = useState<File | null>(null)
  const [cctvPolesFile, setCctvPolesFile] = useState<File | null>(null)
  const [cctvOffsets, setCctvOffsets] = useState('5,10')
  const [cctvStatus, setCctvStatus] = useState<string | null>(null)
  const [cctvResult, setCctvResult] = useState<CctvRunResult | null>(null)

  const [bitcoinSiteIds, setBitcoinSiteIds] = useState('')
  const [bitcoinStatus, setBitcoinStatus] = useState<string | null>(null)
  const [bitcoinResult, setBitcoinResult] = useState<{ buildingCount: number; nearestSubstation: string | null; nearestDistM: number | null } | null>(null)

  function toggleLayer(key: keyof typeof layerToggles) {
    setLayerToggles((prev) => ({ ...prev, [key]: !prev[key] }))
  }
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
      style: getBaseStyle(),
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
    })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl(), 'top-right')

    map.on('load', () => {
      api.currentStatus().then((rows) => {
        setCurrentStatusRows(rows)
        addStatusLayer(map, 'current-status', rows)
      }).catch(() => undefined)
      setMapBounds(readBounds(map))

      // Remember the normal-mode base style's own layers so the
      // satellite toggle can hide them without touching anything this
      // page adds on top (clusters, draw sketches, etc).
      baseLayerIdsRef.current = map.getStyle().layers.map((l) => l.id)
      // Esri satellite imagery + CartoDB label-only overlay — the same
      // two-layer stack the legacy app always rendered (it never had a
      // separate "normal" mode; this rebuild adds that as a real
      // alternative using CartoDB Voyager instead, see STYLE_URL above).
      map.addSource('satellite-base', {
        type: 'raster',
        tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
        tileSize: 256,
        attribution: 'Esri',
      })
      map.addLayer({ id: 'satellite-base-layer', type: 'raster', source: 'satellite-base', layout: { visibility: 'none' } }, baseLayerIdsRef.current[0])
      map.addSource('satellite-labels', {
        type: 'raster',
        tiles: ['https://a.basemaps.cartocdn.com/rastertiles/light_only_labels/{z}/{x}/{y}@2x.png'],
        tileSize: 256,
        attribution: '© OpenStreetMap contributors © CARTO',
      })
      map.addLayer({ id: 'satellite-labels-layer', type: 'raster', source: 'satellite-labels', layout: { visibility: 'none' } })

      map.addSource('heatmap-source', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map.addLayer({
        id: 'heatmap-layer',
        type: 'heatmap',
        source: 'heatmap-source',
        layout: { visibility: 'none' },
        // A small radius/intensity made this look like faint stains
        // rather than a heatmap — bumped both up substantially and
        // pushed the color ramp to go hot much earlier (matching the
        // legacy gradient's blue-by-0.3/red-by-0.95 density curve)
        // instead of staying transparent until density 0.5+.
        paint: {
          'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 0, 20, 9, 45, 15, 70],
          'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 0, 1.5, 9, 3, 15, 4],
          'heatmap-opacity': 0.9,
          'heatmap-color': [
            'interpolate', ['linear'], ['heatmap-density'],
            0, 'rgba(0,0,0,0)',
            0.1, '#1d4ed8',
            0.3, '#22d3ee',
            0.5, '#facc15',
            0.7, '#fb923c',
            0.9, '#dc2626',
            1, '#7f1d1d',
          ],
        },
      })
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
      style: getBaseStyle(),
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
    })
    const right = new maplibregl.Map({
      container: splitRightRef.current,
      style: getBaseStyle(),
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

  // Base map toggle: hide the demotiles vector layers and show the
  // Esri satellite raster underneath everything this page adds, or
  // the reverse.
  useEffect(() => {
    const map = mapRef.current
    if (!map || splitActive || !map.isStyleLoaded() || baseLayerIdsRef.current.length === 0) return
    const satelliteVisible = baseMap === 'satellite'
    map.setLayoutProperty('satellite-base-layer', 'visibility', satelliteVisible ? 'visible' : 'none')
    map.setLayoutProperty('satellite-labels-layer', 'visibility', satelliteVisible ? 'visible' : 'none')
    for (const id of baseLayerIdsRef.current) {
      map.setLayoutProperty(id, 'visibility', satelliteVisible ? 'none' : 'visible')
    }
  }, [baseMap, splitActive, mapBounds])

  // Healthy/Congested toggles stay independently toggleable in the
  // Layers panel, but feed ONE combined cluster source rather than two
  // separately-clustering layers — so two on-screen cluster bubbles
  // never compete at the same spot. Toggling either re-clusters the
  // remaining subset by re-setting the source's data (not by hiding a
  // whole separate layer).
  useEffect(() => {
    const map = mapRef.current
    if (!map || splitActive) return
    const filtered = currentStatusRows.filter(
      (r) => (r.congested && layerToggles.congestedSites) || (!r.congested && layerToggles.healthySites),
    )
    const apply = () => {
      const source = map.getSource('current-status') as maplibregl.GeoJSONSource | undefined
      if (!source) return
      source.setData(statusGeoJson(filtered))
    }
    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)
  }, [currentStatusRows, layerToggles.healthySites, layerToggles.congestedSites, splitActive])

  // Heatmap toggle
  useEffect(() => {
    const map = mapRef.current
    if (!map || splitActive || !map.isStyleLoaded()) return
    if (map.getLayer('heatmap-layer')) map.setLayoutProperty('heatmap-layer', 'visibility', layerToggles.heatmap ? 'visible' : 'none')
  }, [layerToggles.heatmap, splitActive])

  // Heatmap data — fed from the same current-status rows already
  // fetched for the marker layers, just re-requested here since the
  // heatmap needs raw (unclustered) points, not the clustered source.
  useEffect(() => {
    const map = mapRef.current
    if (!map || splitActive || !layerToggles.heatmap) return
    api.currentStatus().then((rows) => {
      const source = map.getSource('heatmap-source') as maplibregl.GeoJSONSource | undefined
      if (!source) return
      source.setData({
        type: 'FeatureCollection',
        features: rows
          .filter((r) => r.congested && r.longitude != null && r.latitude != null)
          .map((r) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [r.longitude as number, r.latitude as number] }, properties: {} })),
      })
    }).catch(() => undefined)
  }, [layerToggles.heatmap, splitActive])

  // Coverage-by-technology wedges — fetched per viewport, one source
  // per generation so each can be toggled independently.
  useEffect(() => {
    const map = mapRef.current
    if (!map || splitActive || !mapBounds) return
    const anyOn = layerToggles.coverage2g || layerToggles.coverage3g || layerToggles.coverage4g || layerToggles.coverage5g
    if (!anyOn) {
      for (const tech of ['2g', '3g', '4g', '5g']) {
        if (map.getLayer(`coverage-${tech}-fill`)) map.setLayoutProperty(`coverage-${tech}-fill`, 'visibility', 'none')
        if (map.getLayer(`coverage-${tech}-dot`)) map.setLayoutProperty(`coverage-${tech}-dot`, 'visibility', 'none')
      }
      return
    }
    api.siteCoverage(mapBounds).then((rows: SiteCoverageRow[]) => {
      const byTech: Record<string, SiteCoverageRow[]> = { '2G': [], '3G': [], '4G': [], '5G': [] }
      for (const r of rows) byTech[r.technology]?.push(r)

      const apply = () => {
        for (const [tech, techRows] of Object.entries(byTech)) {
          const key = tech.toLowerCase()
          const sourceId = `coverage-${key}`
          const toggleOn = layerToggles[`coverage${key}` as keyof typeof layerToggles]
          const data: FeatureCollection = {
            type: 'FeatureCollection',
            features: techRows.map((r) => ({
              type: 'Feature',
              geometry: sectorWedgePolygon([r.longitude, r.latitude], r.coverage_radius_m, r.azimuth),
              properties: { lng: r.longitude, lat: r.latitude },
            })),
          }
          // A real per-cell coverage radius (tens to low-thousands of
          // meters) renders as a sub-pixel sliver at city/region zoom —
          // the wedge fill alone made this look like it "shows
          // nothing" until zoomed all the way into a single site. A
          // small always-visible dot at the cell location guarantees
          // the layer reads as present at any zoom; the wedge becomes
          // visible on top once zoomed in far enough to matter.
          const dotData: FeatureCollection = {
            type: 'FeatureCollection',
            features: techRows.map((r) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [r.longitude, r.latitude] }, properties: {} })),
          }
          const existing = map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined
          if (existing) {
            existing.setData(data)
            ;(map.getSource(`${sourceId}-dots`) as maplibregl.GeoJSONSource).setData(dotData)
            map.setLayoutProperty(`${sourceId}-fill`, 'visibility', toggleOn ? 'visible' : 'none')
            map.setLayoutProperty(`${sourceId}-dot`, 'visibility', toggleOn ? 'visible' : 'none')
            continue
          }
          if (!map.isStyleLoaded()) continue
          map.addSource(sourceId, { type: 'geojson', data })
          map.addLayer({
            id: `${sourceId}-fill`,
            type: 'fill',
            source: sourceId,
            layout: { visibility: toggleOn ? 'visible' : 'none' },
            paint: { 'fill-color': TECH_COLORS[tech], 'fill-opacity': 0.35 },
          })
          map.addSource(`${sourceId}-dots`, { type: 'geojson', data: dotData })
          map.addLayer({
            id: `${sourceId}-dot`,
            type: 'circle',
            source: `${sourceId}-dots`,
            layout: { visibility: toggleOn ? 'visible' : 'none' },
            paint: { 'circle-radius': 4, 'circle-color': TECH_COLORS[tech], 'circle-stroke-width': 1, 'circle-stroke-color': '#ffffff' },
          })
        }
      }
      if (map.isStyleLoaded()) apply()
      else map.once('load', apply)
    }).catch(() => undefined)
  }, [layerToggles.coverage2g, layerToggles.coverage3g, layerToggles.coverage4g, layerToggles.coverage5g, mapBounds, splitActive])

  // Signal-strength band points — empty until real MR/Ookla source
  // files are ingested (no coverage_holes data in dataset_example),
  // wired correctly so it lights up the moment that data exists.
  useEffect(() => {
    const map = mapRef.current
    if (!map || splitActive || !mapBounds) return
    const bands: Array<['high' | 'mid' | 'low', boolean]> = [
      ['high', layerToggles.signalHigh], ['mid', layerToggles.signalMid], ['low', layerToggles.signalLow],
    ]
    for (const [band, on] of bands) {
      const sourceId = `signal-${band}`
      if (!on) {
        if (map.getLayer(`${sourceId}-circle`)) map.setLayoutProperty(`${sourceId}-circle`, 'visibility', 'none')
        continue
      }
      api.coverageHolesByBand(mapBounds, band).then((rows: CoverageHolePoint[]) => {
        const data: FeatureCollection = {
          type: 'FeatureCollection',
          features: rows.map((r) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [r.longitude, r.latitude] }, properties: {} })),
        }
        const apply = () => {
          const existing = map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined
          if (existing) {
            existing.setData(data)
            map.setLayoutProperty(`${sourceId}-circle`, 'visibility', 'visible')
            return
          }
          if (!map.isStyleLoaded()) return
          map.addSource(sourceId, { type: 'geojson', data })
          map.addLayer({
            id: `${sourceId}-circle`,
            type: 'circle',
            source: sourceId,
            paint: { 'circle-radius': 4, 'circle-color': band === 'high' ? '#facc15' : band === 'mid' ? '#f97316' : '#dc2626' },
          })
        }
        if (map.isStyleLoaded()) apply()
        else map.once('load', apply)
      }).catch(() => undefined)
    }
  }, [layerToggles.signalHigh, layerToggles.signalMid, layerToggles.signalLow, mapBounds, splitActive])

  // GeoServer layers — fetch the published list once, add/remove a
  // WMS raster tile source per layer the user actually toggles on.
  useEffect(() => {
    api.geoserverLayers().then(setGeoserverLayerList).catch(() => undefined)
    api.geoserverFixedLayers().then(setFixedLayers).catch(() => undefined)
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || splitActive) return
    for (const layer of geoserverLayerList) {
      const sourceId = `geoserver-${layer.name}`
      const shouldShow = activeGeoserverLayers.has(layer.name)
      if (!shouldShow) {
        if (map.getLayer(`${sourceId}-layer`)) map.removeLayer(`${sourceId}-layer`)
        if (map.getSource(sourceId)) map.removeSource(sourceId)
        continue
      }
      if (map.getSource(sourceId)) continue
      // GeoServer serves WMS tiles directly to the browser — no need
      // to round-trip through our backend, same as the Esri satellite
      // tiles above.
      const geoserverUrl = import.meta.env.VITE_GEOSERVER_URL ?? 'http://localhost:8600/geoserver'
      map.addSource(sourceId, {
        type: 'raster',
        tiles: [`${geoserverUrl}/wms?service=WMS&request=GetMap&layers=${encodeURIComponent(layer.name)}&styles=&format=image/png&transparent=true&version=1.1.1&srs=EPSG:4326&bbox={bbox-epsg-4326}&width=256&height=256`],
        tileSize: 256,
      })
      map.addLayer({ id: `${sourceId}-layer`, type: 'raster', source: sourceId, paint: { 'raster-opacity': 0.7 } })
    }
  }, [activeGeoserverLayers, geoserverLayerList, splitActive])

  function toggleGeoserverLayer(name: string) {
    setActiveGeoserverLayers((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

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

  function panTo(lat: number | null, lng: number | null) {
    if (lat == null || lng == null) return
    const map = mapRef.current
    if (!map) return
    map.flyTo({ center: [lng, lat], zoom: Math.max(map.getZoom(), 14) })
  }

  // Genset/substation routing, single-site mode: either type a site ID
  // or click a point on the map. Substation candidates come from the
  // org's fixed GeoServer substations layer (not user-selectable),
  // not a third-party API — unlike the legacy app, which queried the
  // public Overpass API directly with real site coordinates.
  async function runGenset() {
    setGensetResult(null)
    if (!fixedLayers) {
      setGensetStatus('GeoServer layer configuration not loaded yet — try again in a moment')
      return
    }
    setGensetStatus('Resolving location…')
    try {
      let latitude: number, longitude: number
      if (gensetPickedLatLng) {
        ;[latitude, longitude] = gensetPickedLatLng
      } else {
        const detail = await api.siteDetail(gensetSiteId.trim().toUpperCase())
        if (!detail.site) {
          setGensetStatus(`Site ${gensetSiteId} not found`)
          return
        }
        latitude = detail.site.latitude
        longitude = detail.site.longitude
      }
      setGensetStatus('Querying nearby substations…')
      const features = await api.nearbyGeoserverFeatures(fixedLayers.substations_layer, latitude, longitude, 2500)
      const substations = features.map((f, i) => ({ osm_id: String(f.properties.osm_id ?? i), name: f.name, lat: f.lat, lng: f.lng }))

      if (substations.length === 0) {
        setGensetStatus(`No substations found within 2.5km on layer "${fixedLayers.substations_layer}"`)
        return
      }
      setGensetStatus('Routing to nearest substations…')
      const result = await api.gensetRoute({ site_lat: latitude, site_lng: longitude, substations })
      setGensetResult(result)
      setGensetStatus(result.error ?? `${result.substations_within_2km} substation(s) reachable within 2km of road network`)
    } catch (e) {
      setGensetStatus(e instanceof Error ? e.message : 'Genset lookup failed')
    }
  }

  // Genset routing, bulk mode: upload a spreadsheet of site IDs
  // (legacy's bulk flow), parse the site_id column server-side, then
  // run the same single-site flow for every row and aggregate results
  // — matches the legacy bulk tool's per-site loop.
  async function runGensetBulk() {
    if (!gensetBulkFile) {
      setGensetStatus('Choose an .xlsx or .csv file with a site_id column first')
      return
    }
    if (!fixedLayers) {
      setGensetStatus('GeoServer layer configuration not loaded yet — try again in a moment')
      return
    }
    setGensetBulkResults([])
    setGensetStatus('Reading site IDs from file…')
    try {
      const siteIds = await api.gensetBulkSiteIds(gensetBulkFile)
      if (siteIds.length === 0) {
        setGensetStatus('No site IDs found in that file')
        return
      }
      const results: { siteId: string; result: GensetRouteResult | null; error: string | null }[] = []
      for (let i = 0; i < siteIds.length; i++) {
        const siteId = siteIds[i]
        setGensetStatus(`Processing ${i + 1}/${siteIds.length}: ${siteId}…`)
        try {
          const detail = await api.siteDetail(siteId.toUpperCase())
          if (!detail.site) {
            results.push({ siteId, result: null, error: 'Site not found' })
            continue
          }
          const { latitude, longitude } = detail.site
          const features = await api.nearbyGeoserverFeatures(fixedLayers.substations_layer, latitude, longitude, 2500)
          const substations = features.map((f, j) => ({ osm_id: String(f.properties.osm_id ?? j), name: f.name, lat: f.lat, lng: f.lng }))
          if (substations.length === 0) {
            results.push({ siteId, result: null, error: 'No substations within 2.5km' })
            continue
          }
          const result = await api.gensetRoute({ site_lat: latitude, site_lng: longitude, substations })
          results.push({ siteId, result, error: result.error })
        } catch (e) {
          results.push({ siteId, result: null, error: e instanceof Error ? e.message : 'Failed' })
        }
      }
      setGensetBulkResults(results)
      const okCount = results.filter((r) => r.result && r.result.results.length > 0).length
      setGensetStatus(`${okCount}/${siteIds.length} site(s) routed to a substation`)
    } catch (e) {
      setGensetStatus(e instanceof Error ? e.message : 'Bulk genset processing failed')
    }
  }

  // Map click handler for Genset's "pick a point" single-site mode
  useEffect(() => {
    const map = mapRef.current
    if (!map || !gensetPickMode) return
    function handleClick(e: maplibregl.MapMouseEvent) {
      setGensetPickedLatLng([e.lngLat.lat, e.lngLat.lng])
      setGensetPickMode(false)
    }
    map.on('click', handleClick)
    return () => {
      map.off('click', handleClick)
    }
  }, [gensetPickMode])

  // Marker for the picked point in Genset's single-site mode
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const data: FeatureCollection = {
      type: 'FeatureCollection',
      features: gensetPickedLatLng ? [{ type: 'Feature', geometry: { type: 'Point', coordinates: [gensetPickedLatLng[1], gensetPickedLatLng[0]] }, properties: {} }] : [],
    }
    const apply = () => {
      const existing = map.getSource('genset-picked-point') as maplibregl.GeoJSONSource | undefined
      if (existing) {
        existing.setData(data)
        return
      }
      if (!map.isStyleLoaded()) return
      map.addSource('genset-picked-point', { type: 'geojson', data })
      map.addLayer({
        id: 'genset-picked-point-circle',
        type: 'circle',
        source: 'genset-picked-point',
        paint: { 'circle-radius': 7, 'circle-color': '#f97316', 'circle-stroke-width': 2, 'circle-stroke-color': '#ffffff' },
      })
    }
    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)
  }, [gensetPickedLatLng])

  // CCTV planning: requires the same file uploads the legacy tool did
  // (building/parking/poles GeoJSON, no single-site flow available
  // since coverage depends on the whole area's geometry).
  async function runCctv() {
    if (!cctvBuildingFile || !cctvParkingFile || !cctvPolesFile) {
      setCctvStatus('Building, parking, and poles files are all required')
      return
    }
    setCctvResult(null)
    setCctvStatus('Running pipeline…')
    try {
      const [building, parking, poles] = await Promise.all(
        [cctvBuildingFile, cctvParkingFile, cctvPolesFile].map(async (f) => JSON.parse(await f.text())),
      )
      const offsets = cctvOffsets.split(',').map((s) => Number(s.trim())).filter((n) => Number.isFinite(n))
      const result = await api.cctvRun({
        building, parking, poles,
        cameras: [
          { camera_type: 'PTZ', hfov_deg: 90, range_m: 50, unit_price_rm: 3500 },
          { camera_type: 'Fixed', hfov_deg: 60, range_m: 30, unit_price_rm: 1800 },
        ],
        offsets: offsets.length > 0 ? offsets : [5],
      })
      setCctvResult(result)
      setCctvStatus(`${result.candidate_cctv.features.length} candidate camera position(s) found`)
    } catch (e) {
      setCctvStatus(e instanceof Error ? e.message : 'CCTV pipeline failed — check that uploaded files are valid GeoJSON')
    }
  }

  // Illegal Bitcoin-mining detection: triangulate a buffer from 2-3
  // selected sites, then check our own GeoServer-published
  // buildings/substations layers for anything nearby — the theory
  // (ported from the legacy app's agent.py framing) being that heavy,
  // unexplained congestion near a substation can indicate
  // unauthorized power draw. Unlike the legacy app, which queried the
  // public Overpass API directly from the browser with real site
  // coordinates, this stays entirely within our own infrastructure.
  async function runBitcoinMining() {
    const ids = bitcoinSiteIds.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean)
    if (ids.length < 2 || ids.length > 3) {
      setBitcoinStatus('Select 2 or 3 site IDs (comma-separated)')
      return
    }
    if (!fixedLayers) {
      setBitcoinStatus('GeoServer layer configuration not loaded yet — try again in a moment')
      return
    }
    setBitcoinResult(null)
    setBitcoinStatus('Looking up sites…')
    try {
      const details = await Promise.all(ids.map((id) => api.siteDetail(id)))
      const points = details.filter((d) => d.site).map((d) => [d.site!.latitude, d.site!.longitude] as [number, number])
      if (points.length < 2) {
        setBitcoinStatus('Could not resolve enough of those site IDs')
        return
      }
      const centerLat = points.reduce((s, p) => s + p[0], 0) / points.length
      const centerLng = points.reduce((s, p) => s + p[1], 0) / points.length
      const radiusM = Math.max(...points.map((p) => haversineDistanceMeters([centerLng, centerLat], [p[1], p[0]]))) || 500

      setBitcoinStatus('Querying nearby buildings and substations…')
      const [buildings, substations] = await Promise.all([
        api.nearbyGeoserverFeatures(fixedLayers.buildings_layer, centerLat, centerLng, radiusM),
        api.nearbyGeoserverFeatures(fixedLayers.substations_layer, centerLat, centerLng, radiusM * 3),
      ])

      let nearestSubstation: string | null = null
      let nearestDistM: number | null = null
      for (const sub of substations) {
        const dist = haversineDistanceMeters([centerLng, centerLat], [sub.lng, sub.lat])
        if (nearestDistM === null || dist < nearestDistM) {
          nearestDistM = dist
          nearestSubstation = sub.name
        }
      }
      setBitcoinResult({ buildingCount: buildings.length, nearestSubstation, nearestDistM })
      setBitcoinStatus(
        buildings.length === 0 && substations.length === 0
          ? `No data on layers "${fixedLayers.buildings_layer}"/"${fixedLayers.substations_layer}" yet — publish them in GeoServer to use this tool`
          : `${buildings.length} candidate building(s) found within ${fmtDistance(radiusM)} of the triangulated center`,
      )

      const map = mapRef.current
      if (map) {
        const apply = () => {
          const data: FeatureCollection = {
            type: 'FeatureCollection',
            features: buildings.map((b) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [b.lng, b.lat] }, properties: {} })),
          }
          const existing = map.getSource('bitcoin-buildings') as maplibregl.GeoJSONSource | undefined
          if (existing) {
            existing.setData(data)
          } else {
            map.addSource('bitcoin-buildings', { type: 'geojson', data })
            map.addLayer({ id: 'bitcoin-buildings-circle', type: 'circle', source: 'bitcoin-buildings', paint: { 'circle-radius': 5, 'circle-color': '#dc2626' } })
          }
        }
        if (map.isStyleLoaded()) apply()
        else map.once('load', apply)
      }
    } catch (e) {
      setBitcoinStatus(e instanceof Error ? e.message : 'Bitcoin-mining lookup failed')
    }
  }

  // Render genset route lines — single result, or all routes from a
  // bulk run combined.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const allResults = gensetResult ? [gensetResult] : gensetBulkResults.map((r) => r.result).filter((r): r is GensetRouteResult => r !== null)
    if (allResults.length === 0) return
    const data: FeatureCollection = {
      type: 'FeatureCollection',
      features: allResults.flatMap((res) =>
        res.results.map((r) => ({ type: 'Feature' as const, geometry: { type: 'LineString' as const, coordinates: r.route_coords }, properties: { name: r.name } })),
      ),
    }
    const apply = () => {
      const existing = map.getSource('genset-routes') as maplibregl.GeoJSONSource | undefined
      if (existing) {
        existing.setData(data)
        return
      }
      if (!map.isStyleLoaded()) return
      map.addSource('genset-routes', { type: 'geojson', data })
      map.addLayer({ id: 'genset-routes-line', type: 'line', source: 'genset-routes', paint: { 'line-color': '#f97316', 'line-width': 3 } })
    }
    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)
  }, [gensetResult, gensetBulkResults])

  return (
    <div className="space-y-4">
      <GlassPanel className="relative z-30 flex flex-wrap items-start gap-3">
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
            <div className="relative z-30 flex flex-col items-center">
              <p className="mb-1 whitespace-nowrap text-[10px] font-semibold uppercase tracking-wider text-white/45">Draw</p>
              <button
                onClick={() => {
                  setDrawMenuOpen((v) => !v)
                  setGensetMenuOpen(false)
                }}
                title="Draw an annotation"
                className={`flex h-9 w-9 items-center justify-center rounded-xl ${
                  tool !== 'none' ? 'bg-sky-400 text-ink-900' : 'border border-white/20 text-white/80'
                }`}
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 5v14M5 12h14" />
                </svg>
              </button>

              {drawMenuOpen && (
                <div className="absolute left-0 top-full z-30 mt-2 flex gap-1.5 rounded-2xl border border-white/15 bg-ink-900/95 p-2 backdrop-blur-xl">
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
            <div className="flex flex-col items-center">
              <p className="mb-1 whitespace-nowrap text-[10px] font-semibold uppercase tracking-wider text-white/45">&nbsp;</p>
              {tool !== 'none' ? (
                <button
                  onClick={() => {
                    setTool('none')
                    setDraftPoints([])
                  }}
                  className="h-9 rounded-xl border border-white/20 px-3 text-xs font-semibold text-white/70"
                >
                  Cancel draw
                </button>
              ) : (
                <div className="h-9" />
              )}
            </div>

            <div className="flex flex-col items-center">
              <p className="mb-1 whitespace-nowrap text-[10px] font-semibold uppercase tracking-wider text-white/45">Measure</p>
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
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 17 17 3M5 19l2-2M9 15l2-2M13 11l2-2" />
                  <path d="M17 3l4 4-14 14-4-4z" />
                </svg>
              </button>
            </div>

            <div className="relative z-30 flex flex-col items-center">
              <p className="mb-1 whitespace-nowrap text-[10px] font-semibold uppercase tracking-wider text-white/45">Genset</p>
              <button
                onClick={() => {
                  setGensetMenuOpen((v) => !v)
                  setDrawMenuOpen(false)
                }}
                title="Genset/substation routing"
                className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/20 text-white/80"
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M13 2 3 14h7l-1 8 11-12h-7l1-8z" />
                </svg>
              </button>
              {gensetMenuOpen && (
                <div className="absolute left-0 top-full z-30 mt-2 w-36 rounded-2xl border border-white/15 bg-ink-900/95 p-2 text-xs backdrop-blur-xl">
                  <button
                    onClick={() => {
                      setRightPanel('genset-single')
                      setGensetMenuOpen(false)
                    }}
                    className="block w-full rounded-lg px-2.5 py-1.5 text-left text-white/80 hover:bg-white/10"
                  >
                    Single site
                  </button>
                  <button
                    onClick={() => {
                      setActiveToolPanel('genset-bulk')
                      setGensetMenuOpen(false)
                    }}
                    className="block w-full rounded-lg px-2.5 py-1.5 text-left text-white/80 hover:bg-white/10"
                  >
                    Bulk (xlsx/csv)
                  </button>
                </div>
              )}
            </div>

            <div className="flex flex-col items-center">
              <p className="mb-1 whitespace-nowrap text-[10px] font-semibold uppercase tracking-wider text-white/45">CCTV</p>
              <button
                onClick={() => setActiveToolPanel('cctv')}
                title="CCTV camera planning"
                className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/20 text-white/80"
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="7" width="13" height="10" rx="2" />
                  <path d="M16 10.5 21 7v10l-5-3.5" />
                </svg>
              </button>
            </div>

            <div className="flex flex-col items-center">
              <p className="mb-1 whitespace-nowrap text-[10px] font-semibold uppercase tracking-wider text-white/45">Power check</p>
              <button
                onClick={() => setRightPanel((v) => (v === 'bitcoin' ? 'none' : 'bitcoin'))}
                title="Unauthorized power-draw check"
                className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/20 text-white/80"
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="9" />
                  <path d="M9.5 9h2l-1 3h2l-2.5 4M14.5 9h-1" />
                </svg>
              </button>
            </div>
            {(tool === 'line' || tool === 'polygon') && (
              <button
                onClick={finishDraft}
                className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-ink-900"
              >
                Finish ({draftPoints.length} pts)
              </button>
            )}

            {/* Far-right zone: measure results, and the Genset single-site
                /power-draw-check inline panels — inline rather than a
                centered modal so the map stays visible to click a site. */}
            <div className="ml-auto flex items-end gap-3">
              {measureActive && (
                <div>
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/45">&nbsp;</p>
                  <button
                    onClick={() => setMeasurePoints([])}
                    className="h-9 rounded-xl border border-white/20 px-3 text-xs font-semibold text-white/70"
                  >
                    Clear points
                  </button>
                </div>
              )}
              {measurePoints.length >= 2 && (
                <div>
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/45">&nbsp;</p>
                  <div className="flex h-9 items-center rounded-xl border border-sky-400/30 bg-sky-400/10 px-3 text-xs">
                    <span className="text-white/55">Total distance </span>
                    <span className="ml-1 font-semibold text-sky-300">
                      {fmtDistance(measurePoints.slice(1).reduce((sum, p, i) => sum + haversineDistanceMeters(measurePoints[i], p), 0))}
                    </span>
                  </div>
                </div>
              )}

              {rightPanel === 'genset-single' && (
                <div className="w-72">
                  <div className="mb-1 flex items-center justify-between">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-white/45">Genset — single site</p>
                    <button
                      onClick={() => {
                        setRightPanel('none')
                        setGensetResult(null)
                        setGensetStatus(null)
                        setGensetPickMode(false)
                        setGensetPickedLatLng(null)
                      }}
                      className="text-white/40 hover:text-white"
                    >
                      <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M6 6l12 12M18 6 6 18" />
                      </svg>
                    </button>
                  </div>
                  <div className="rounded-xl border border-white/15 bg-white/5 p-3">
                    <div className="mb-2 flex gap-1.5">
                      <button
                        onClick={() => {
                          setGensetPickMode((v) => !v)
                          setGensetPickedLatLng(null)
                        }}
                        className={`flex-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold ${
                          gensetPickMode ? 'bg-sky-400 text-ink-900' : 'border border-white/20 text-white/70'
                        }`}
                      >
                        {gensetPickMode ? 'Click a point…' : 'Click site on map'}
                      </button>
                      {gensetPickedLatLng && (
                        <button onClick={() => setGensetPickedLatLng(null)} className="rounded-lg border border-white/20 px-2.5 py-1.5 text-xs font-semibold text-white/70">
                          Clear
                        </button>
                      )}
                    </div>
                    {gensetPickedLatLng ? (
                      <p className="mb-2 rounded-lg bg-white/5 px-2.5 py-1.5 text-xs text-white/70">
                        Pinned: {gensetPickedLatLng[0].toFixed(5)}, {gensetPickedLatLng[1].toFixed(5)}
                      </p>
                    ) : (
                      <input
                        value={gensetSiteId}
                        onChange={(e) => setGensetSiteId(e.target.value)}
                        placeholder="Or search by site ID — e.g. N00377"
                        className="mb-2 w-full rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs focus:border-sky-400/60 focus:outline-none"
                      />
                    )}
                    <button
                      onClick={runGenset}
                      className="mb-2 w-full rounded-lg bg-gradient-to-r from-accent-400 to-accent-500 px-3 py-1.5 text-xs font-semibold text-ink-900"
                    >
                      Find route
                    </button>
                    {gensetStatus && <p className="mb-1.5 text-[11px] text-white/60">{gensetStatus}</p>}
                    {gensetResult && gensetResult.results.length > 0 && (
                      <ul className="max-h-32 space-y-1 overflow-y-auto text-[11px]">
                        {gensetResult.results.map((r) => (
                          <li key={r.osm_id} className="rounded-lg bg-white/5 px-2 py-1">
                            <span className="font-semibold">{r.name}</span>
                            <span className="text-white/55"> — {r.road_dist_km} km</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              )}

              {rightPanel === 'bitcoin' && (
                <div className="w-72">
                  <div className="mb-1 flex items-center justify-between">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-white/45">Power-draw check</p>
                    <button
                      onClick={() => {
                        setRightPanel('none')
                        setBitcoinResult(null)
                        setBitcoinStatus(null)
                      }}
                      className="text-white/40 hover:text-white"
                    >
                      <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M6 6l12 12M18 6 6 18" />
                      </svg>
                    </button>
                  </div>
                  <div className="rounded-xl border border-white/15 bg-white/5 p-3">
                    <input
                      value={bitcoinSiteIds}
                      onChange={(e) => setBitcoinSiteIds(e.target.value)}
                      placeholder="2-3 site IDs, comma-separated"
                      className="mb-2 w-full rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs focus:border-sky-400/60 focus:outline-none"
                    />
                    <button
                      onClick={runBitcoinMining}
                      className="mb-2 w-full rounded-lg bg-gradient-to-r from-accent-400 to-accent-500 px-3 py-1.5 text-xs font-semibold text-ink-900"
                    >
                      Check
                    </button>
                    {bitcoinStatus && <p className="mb-1.5 text-[11px] text-white/60">{bitcoinStatus}</p>}
                    {bitcoinResult && (
                      <div className="rounded-lg bg-white/5 px-2.5 py-1.5 text-[11px]">
                        <p>Buildings: <span className="font-semibold">{bitcoinResult.buildingCount}</span></p>
                        {bitcoinResult.nearestSubstation && (
                          <p>
                            Nearest sub: <span className="font-semibold">{bitcoinResult.nearestSubstation}</span>
                            {bitcoinResult.nearestDistM != null && ` (${fmtDistance(bitcoinResult.nearestDistM)})`}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </>
        )}

        {status && <p className="text-sm text-white/70">{status}</p>}
      </GlassPanel>

      <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
        {!splitActive && (
          <div className="relative h-[55vh] w-full">
            <div ref={containerRef} className="h-full w-full overflow-hidden rounded-3xl border border-white/15" />

            {/* Layers — controls: base map mode + which layers are on.
                Top-left. */}
            <div className="absolute left-3 top-3 z-10">
              <button
                onClick={() => setLayersOpen((v) => !v)}
                title="Layers"
                className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/20 bg-ink-900/90 text-white/80 backdrop-blur-sm"
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
                </svg>
              </button>

              {layersOpen && (
                <div className="mt-2 max-h-[48vh] w-64 overflow-y-auto rounded-2xl border border-white/15 bg-ink-900/95 p-3 text-xs text-white/85 shadow-[0_8px_32px_-8px_rgba(0,0,0,0.6)] backdrop-blur-xl">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="font-display text-sm font-semibold text-white">Layers</p>
                    <button onClick={() => setLayersOpen(false)} className="text-white/40 hover:text-white">
                      <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M6 6l12 12M18 6 6 18" />
                      </svg>
                    </button>
                  </div>

                  <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-white/45">Map</p>
                  <div className="mb-3 flex gap-1.5">
                    {(['normal', 'satellite'] as const).map((m) => (
                      <button
                        key={m}
                        onClick={() => setBaseMap(m)}
                        className={`flex-1 rounded-lg px-2 py-1.5 capitalize ${baseMap === m ? 'bg-sky-400 text-ink-900 font-semibold' : 'border border-white/15 text-white/70'}`}
                      >
                        {m}
                      </button>
                    ))}
                  </div>

                  <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-white/45">Layers</p>
                  <div className="mb-3 space-y-1">
                    {LAYER_LEGEND_ITEMS.map(([key, label, swatch]) => (
                      <label key={key} className={`flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-white/10 ${layerToggles[key] ? '' : 'opacity-50'}`}>
                        <input type="checkbox" checked={layerToggles[key]} onChange={() => toggleLayer(key)} className="accent-sky-400" />
                        {swatch}
                        {label}
                      </label>
                    ))}
                  </div>

                  <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-white/45">GeoServer</p>
                  {geoserverLayerList.length === 0 ? (
                    <p className="text-white/40">No layers published (GeoServer not reachable, or nothing published yet).</p>
                  ) : (
                    <div className="space-y-1">
                      {geoserverLayerList.map((layer) => (
                        <label key={layer.name} className={`flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-white/10 ${activeGeoserverLayers.has(layer.name) ? '' : 'opacity-50'}`}>
                          <input
                            type="checkbox"
                            checked={activeGeoserverLayers.has(layer.name)}
                            onChange={() => toggleGeoserverLayer(layer.name)}
                            className="accent-sky-400"
                          />
                          {layer.title}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Legends — read-only, dynamic: only shows a color key for
                whichever layers are actually toggled on above (base map
                mode isn't a "layer" so it's excluded). Bottom-left,
                collapsible, open by default. */}
            <div className="absolute bottom-3 left-3 z-10">
              {legendsOpen && (
                <div className="mb-2 max-h-[40vh] w-56 overflow-y-auto rounded-2xl border border-white/15 bg-ink-900/95 p-3 text-xs text-white/85 shadow-[0_8px_32px_-8px_rgba(0,0,0,0.6)] backdrop-blur-xl">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="font-display text-sm font-semibold text-white">Legends</p>
                    <button onClick={() => setLegendsOpen(false)} className="text-white/40 hover:text-white">
                      <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M6 6l12 12M18 6 6 18" />
                      </svg>
                    </button>
                  </div>
                  {(() => {
                    const activeLayers = LAYER_LEGEND_ITEMS.filter(([key]) => layerToggles[key])
                    const activeGeo = geoserverLayerList.filter((l) => activeGeoserverLayers.has(l.name))
                    if (activeLayers.length === 0 && activeGeo.length === 0) {
                      return <p className="text-white/40">No layers toggled on.</p>
                    }
                    return (
                      <div className="space-y-1">
                        {activeLayers.map(([key, label, swatch]) => (
                          <div key={key} className="flex items-center gap-2 px-1.5 py-0.5">
                            {swatch}
                            {label}
                          </div>
                        ))}
                        {activeGeo.map((l) => (
                          <div key={l.name} className="flex items-center gap-2 px-1.5 py-0.5">
                            <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
                            {l.title}
                          </div>
                        ))}
                      </div>
                    )
                  })()}
                </div>
              )}

              <button
                onClick={() => setLegendsOpen((v) => !v)}
                title="Legends"
                className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/20 bg-ink-900/90 text-white/80 backdrop-blur-sm"
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 6h16M4 12h10M4 18h7" />
                </svg>
              </button>
            </div>
          </div>
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
            <p className="text-[10px] text-white/35">
              The viewport panel below and the map's marker count can be lower than this — a known
              gap in the source data means some sites with congestion records have no coordinates,
              so they can't be plotted or counted in any viewport.
            </p>
            <div>
              <p className="text-white/55">Total CAPEX needed</p>
              <p className="font-semibold">{fmtCurrency(overview?.total_capex)}</p>
            </div>
            <div className="border-t border-white/10 pt-2.5">
              <p className="mb-1 text-white/55">Worst congested sectors</p>
              {overview && overview.worst_congested_sectors.length > 0 ? (
                <div className="max-h-40 overflow-y-auto rounded-lg bg-white/5">
                  <table className="w-full text-left text-[11px]">
                    <thead className="sticky top-0 bg-ink-900/95 text-white/40">
                      <tr>
                        <th className="px-2 py-1 font-normal">#</th>
                        <th className="px-2 py-1 font-normal">Sector</th>
                        <th className="px-2 py-1 font-normal">Region</th>
                        <th className="px-2 py-1 text-right font-normal">Weeks</th>
                      </tr>
                    </thead>
                    <tbody>
                      {overview.worst_congested_sectors.map((s, i) => (
                        <tr
                          key={s.zoom_sector_id}
                          onClick={() => panTo(s.latitude, s.longitude)}
                          className={`border-t border-white/5 ${s.latitude != null ? 'cursor-pointer hover:bg-white/10' : 'opacity-50'}`}
                        >
                          <td className="px-2 py-1 text-white/40">{i + 1}</td>
                          <td className="px-2 py-1 font-semibold">{s.zoom_sector_id}</td>
                          <td className="px-2 py-1 text-white/55">{s.region}</td>
                          <td className="px-2 py-1 text-right text-white/55">{s.congested_weeks}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs text-white/40">—</p>
              )}
            </div>
            <div>
              <p className="mb-1 text-white/55">Worst Ookla clusters</p>
              {overview && overview.worst_ookla_clusters.length > 0 ? (
                <div className="max-h-40 overflow-y-auto rounded-lg bg-white/5">
                  <table className="w-full text-left text-[11px]">
                    <thead className="sticky top-0 bg-ink-900/95 text-white/40">
                      <tr>
                        <th className="px-2 py-1 font-normal">#</th>
                        <th className="px-2 py-1 font-normal">Cluster</th>
                        <th className="px-2 py-1 text-right font-normal">Points</th>
                        <th className="px-2 py-1 text-right font-normal">Avg dBm</th>
                      </tr>
                    </thead>
                    <tbody>
                      {overview.worst_ookla_clusters.map((c, i) => (
                        <tr
                          key={c.cluster_id}
                          onClick={() => panTo(c.latitude, c.longitude)}
                          className={`border-t border-white/5 ${c.latitude != null ? 'cursor-pointer hover:bg-white/10' : 'opacity-50'}`}
                        >
                          <td className="px-2 py-1 text-white/40">{i + 1}</td>
                          <td className="px-2 py-1 font-semibold">#{c.cluster_id}</td>
                          <td className="px-2 py-1 text-right text-white/55">{c.point_count}</td>
                          <td className="px-2 py-1 text-right text-white/55">{fmt(c.avg_signal)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs text-white/40">—</p>
              )}
            </div>
            <div>
              <p className="mb-1 text-white/55">Worst MR clusters</p>
              {overview && overview.worst_mr_clusters.length > 0 ? (
                <div className="max-h-40 overflow-y-auto rounded-lg bg-white/5">
                  <table className="w-full text-left text-[11px]">
                    <thead className="sticky top-0 bg-ink-900/95 text-white/40">
                      <tr>
                        <th className="px-2 py-1 font-normal">#</th>
                        <th className="px-2 py-1 font-normal">Cluster</th>
                        <th className="px-2 py-1 text-right font-normal">Points</th>
                        <th className="px-2 py-1 text-right font-normal">Avg dBm</th>
                      </tr>
                    </thead>
                    <tbody>
                      {overview.worst_mr_clusters.map((c, i) => (
                        <tr
                          key={c.cluster_id}
                          onClick={() => panTo(c.latitude, c.longitude)}
                          className={`border-t border-white/5 ${c.latitude != null ? 'cursor-pointer hover:bg-white/10' : 'opacity-50'}`}
                        >
                          <td className="px-2 py-1 text-white/40">{i + 1}</td>
                          <td className="px-2 py-1 font-semibold">#{c.cluster_id}</td>
                          <td className="px-2 py-1 text-right text-white/55">{c.point_count}</td>
                          <td className="px-2 py-1 text-right text-white/55">{fmt(c.avg_signal)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs text-white/40">—</p>
              )}
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

      {activeToolPanel === 'genset-bulk' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/60 backdrop-blur-sm">
          <GlassPanel className="w-full max-w-sm">
            <p className="mb-1 font-display text-sm font-semibold">Genset/substation routing — bulk</p>
            <p className="mb-3.5 text-[11px] text-white/40">
              substations from {fixedLayers ? `"${fixedLayers.substations_layer}"` : 'GeoServer'}
            </p>
            <div className="mb-3">
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
                Spreadsheet with a site_id column
              </label>
              <input
                type="file"
                accept=".xlsx,.xls,.csv"
                onChange={(e) => setGensetBulkFile(e.target.files?.[0] ?? null)}
                className="w-full text-xs text-white/70"
              />
              {gensetBulkFile && <p className="mt-0.5 text-[11px] text-emerald-300">{gensetBulkFile.name}</p>}
            </div>
            {gensetStatus && <p className="mb-3 text-xs text-white/70">{gensetStatus}</p>}
            {gensetBulkResults.length > 0 && (
              <div className="mb-3 max-h-48 overflow-y-auto rounded-xl bg-white/5">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-ink-900/95 text-white/45">
                    <tr>
                      <th className="px-2.5 py-1.5">Site ID</th>
                      <th className="px-2.5 py-1.5">Nearest substation</th>
                      <th className="px-2.5 py-1.5">Distance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gensetBulkResults.map((r) => {
                      const best = r.result?.results[0]
                      return (
                        <tr key={r.siteId} className="border-t border-white/5">
                          <td className="px-2.5 py-1.5 font-semibold">{r.siteId}</td>
                          <td className="px-2.5 py-1.5 text-white/70">{best ? best.name : r.error ?? '—'}</td>
                          <td className="px-2.5 py-1.5 text-white/70">{best ? `${best.road_dist_km} km` : '—'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button
                onClick={() => {
                  setActiveToolPanel('none')
                  setGensetStatus(null)
                  setGensetBulkResults([])
                }}
                className="rounded-xl border border-white/20 px-4 py-2 text-sm font-semibold text-white/70"
              >
                Close
              </button>
              <button
                onClick={runGensetBulk}
                className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-ink-900"
              >
                Process file
              </button>
            </div>
          </GlassPanel>
        </div>
      )}

      {activeToolPanel === 'cctv' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/60 backdrop-blur-sm">
          <GlassPanel className="w-full max-w-sm">
            <p className="mb-3.5 font-display text-sm font-semibold">CCTV camera planning</p>
            {([
              ['Building footprints (GeoJSON)', cctvBuildingFile, setCctvBuildingFile, 'cctv-building-input'],
              ['Parking areas (GeoJSON)', cctvParkingFile, setCctvParkingFile, 'cctv-parking-input'],
              ['Existing poles (GeoJSON)', cctvPolesFile, setCctvPolesFile, 'cctv-poles-input'],
            ] as const).map(([label, file, setFile, inputId]) => (
              <div key={label} className="mb-2.5">
                <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">{label}</label>
                <input
                  id={inputId}
                  type="file"
                  accept=".geojson,.json"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="hidden"
                />
                <label
                  htmlFor={inputId}
                  className={`flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2 text-xs font-semibold ${
                    file ? 'border-emerald-400/40 bg-emerald-400/10 text-emerald-300' : 'border-white/20 bg-white/5 text-white/80 hover:bg-white/10'
                  }`}
                >
                  <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 16V4M7 9l5-5 5 5M5 20h14" />
                  </svg>
                  {file ? file.name : 'Choose file…'}
                </label>
              </div>
            ))}
            <div className="mb-3">
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">
                Setback offsets (meters, comma-separated)
              </label>
              <input
                value={cctvOffsets}
                onChange={(e) => setCctvOffsets(e.target.value)}
                className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm focus:border-sky-400/60 focus:outline-none"
              />
            </div>
            {cctvStatus && <p className="mb-3 text-xs text-white/70">{cctvStatus}</p>}
            {cctvResult && cctvResult.camera_cost_summary.features.length > 0 && (
              <ul className="mb-3 space-y-1 text-xs">
                {cctvResult.camera_cost_summary.features.map((f, i) => (
                  <li key={i} className="rounded-lg bg-white/5 px-2.5 py-1.5">
                    <span className="font-semibold">{String(f.properties?.camera_type)}</span>
                    <span className="text-white/55"> — {String(f.properties?.count)}× — {fmtCurrency(Number(f.properties?.total_cost_rm))}</span>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex justify-end gap-2">
              <button
                onClick={() => { setActiveToolPanel('none'); setCctvResult(null); setCctvStatus(null) }}
                className="rounded-xl border border-white/20 px-4 py-2 text-sm font-semibold text-white/70"
              >
                Close
              </button>
              <button
                onClick={runCctv}
                className="flex items-center gap-2 rounded-xl bg-emerald-500 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-400"
              >
                <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor">
                  <path d="M8 5v14l11-7z" />
                </svg>
                Run CCTV Pipeline
              </button>
            </div>
          </GlassPanel>
        </div>
      )}

    </div>
  )
}
