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
  type ForecastRow,
  type GensetRouteResult,
  type GeoserverLayer,
  type MapBounds,
  type MapStats,
  type OverviewStats,
  type SiteCoverageRow,
  type UserOut,
} from '../lib/api'
import { addStatusLayer, fmt, getBaseStyle, statusGeoJson } from '../lib/mapLayers'
import { ForecastModal } from '../components/ForecastModal'
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

function MapStatsPanel({ title, stats, compact = false }: { title: string; stats: MapStats | null; compact?: boolean }) {
  return (
    <GlassPanel>
      <p className="mb-3 font-display text-sm font-semibold">{title}</p>
      {!stats ? (
        <p className="text-sm text-white/50">Pan or zoom the map to load stats.</p>
      ) : (
        <div className={`grid gap-3 ${compact ? 'grid-cols-4' : 'grid-cols-2 sm:grid-cols-3'}`}>
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
          {!compact && (
            <>
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
            </>
          )}
        </div>
      )}
    </GlassPanel>
  )
}

export function MapPage() {
  const containerRef = useRef<HTMLDivElement>(null)
  const splitLeftRef = useRef<HTMLDivElement>(null)
  const splitMiddleRef = useRef<HTMLDivElement>(null)
  const splitRightRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const splitLeftMapRef = useRef<maplibregl.Map | null>(null)
  const splitMiddleMapRef = useRef<maplibregl.Map | null>(null)
  const splitRightMapRef = useRef<maplibregl.Map | null>(null)

  const [splitMode, setSplitMode] = useState<'none' | 'two' | 'three'>('none')
  const splitActive = splitMode !== 'none'
  const [forecastYear, setForecastYear] = useState(new Date().getFullYear())
  const [forecastWeek, setForecastWeek] = useState(13)
  const [availableWeeks, setAvailableWeeks] = useState<{ year: number; week: number }[]>([])
  const [mapFilterKey, setMapFilterKey] = useState<string>('latest')  // 'latest' or 'YYYY-WW'
  const [pastKey, setPastKey] = useState<string>('')
  // Pricing — two inputs matching legacy: material + engineering per 100 m
  const [matPer100m, setMatPer100m] = useState(850)
  const [engPer100m, setEngPer100m] = useState(200)

  // Derive year/week from the selected key strings
  const parseKey = (key: string): { year: number; week: number } | null => {
    if (!key || key === 'latest') return null
    const [y, w] = key.split('-').map(Number)
    return { year: y, week: w }
  }
  const mapFilter = parseKey(mapFilterKey)
  const mapFilterYear = mapFilter?.year ?? null
  const mapFilterWeek = mapFilter?.week ?? null
  const pastFilter = parseKey(pastKey)
  const pastYear = pastFilter?.year ?? new Date().getFullYear()
  const pastWeek = pastFilter?.week ?? 1

  const [forecastModal, setForecastModal] = useState<{ siteId: string; rows: ForecastRow[] } | null>(null)

  // Register a global so the MapLibre popup's "Full Forecast" button can open
  // the React modal. The popup is injected HTML so it can't call React state
  // directly — window is the only bridge available.
  const setForecastModalRef = useRef(setForecastModal)
  setForecastModalRef.current = setForecastModal
  useEffect(() => {
    ;(window as unknown as Record<string, unknown>).swOpenForecastModal = (siteId: string) => {
      api.siteDetail(siteId).then((d) => {
        setForecastModalRef.current({ siteId, rows: d.forecast })
      }).catch(() => undefined)
    }
    return () => { delete (window as unknown as Record<string, unknown>).swOpenForecastModal }
  }, [])

  const [users, setUsers] = useState<UserOut[]>([])
  const [overview, setOverview] = useState<OverviewStats | null>(null)
  const [mapBounds, setMapBounds] = useState<MapBounds | null>(null)
  const [currentStats, setCurrentStats] = useState<MapStats | null>(null)
  const [currentStatusRows, setCurrentStatusRows] = useState<CurrentStatusRow[]>([])
  const [forecastStats, setForecastStats] = useState<MapStats | null>(null)
  const [pastStats, setPastStats] = useState<MapStats | null>(null)
  const [tool, setTool] = useState<DrawTool>('none')
  const [drawMenuOpen, setDrawMenuOpen] = useState(false)
  const [measureActive, setMeasureActive] = useState(false)
  const [measurePoints, setMeasurePoints] = useState<[number, number][]>([])
  const baseLayerIdsRef = useRef<string[]>([])

  const [layersOpen, setLayersOpen] = useState(false)
  const [legendsOpen, setLegendsOpen] = useState(true)

  const LAYER_LEGEND_ITEMS = [
    ['healthySites', 'Healthy sites', <span key="sw" className="h-2.5 w-2.5 rounded-full border-2 border-[#60a5fa] bg-white/15" />],
    ['congestedSites', 'Congested sites', <span key="sw" className="h-2.5 w-2.5 rounded-full border-2 border-[#f87171] bg-white/15" />],
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

  // Unified tool drawer — right-side panel on desktop, bottom sheet on mobile
  const [toolDrawer, setToolDrawer] = useState<'none' | 'genset' | 'cctv' | 'bitcoin'>('none')
  const [gensetTab, setGensetTab] = useState<'single' | 'bulk'>('single')

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
  // Default camera specs — editable in the drawer before running
  const [cctvCameras, setCctvCameras] = useState([
    { camera_type: 'Type A', hfov_deg: 90, range_m: 30, unit_price_rm: 500 },
  ])

  // Bitcoin / illegal-mining power check
  const [btcMode, setBtcMode] = useState<2 | 3>(2)
  const [btcPickMode, setBtcPickMode] = useState(false)
  const [btcSites, setBtcSites] = useState<{ site_id: string; lat: number; lng: number }[]>([])
  const [btcSearch, setBtcSearch] = useState('')
  const [btcStatus, setBtcStatus] = useState<string | null>(null)
  const [btcResult, setBtcResult] = useState<{ buildingCount: number; radiusKm: number; substations: { name: string; distM: number }[] } | null>(null)

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

  useEffect(() => {
    api.availableWeeks().then((weeks) => {
      setAvailableWeeks(weeks)
      // Pre-select the most recent past week as the default for the past pane
      if (weeks.length > 0) setPastKey(`${weeks[0].year}-${weeks[0].week}`)
    }).catch(() => undefined)
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
      api.currentStatus(mapFilterYear ?? undefined, mapFilterWeek ?? undefined).then((rows) => {
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

  // Split mode: two-pane = CURRENT | FORECAST; three-pane = PAST | CURRENT | FORECAST
  useEffect(() => {
    if (!splitActive || !splitLeftRef.current || !splitRightRef.current) return
    if (splitMode === 'three' && !splitMiddleRef.current) return

    const makeMap = (container: HTMLDivElement) => new maplibregl.Map({
      container,
      style: getBaseStyle(),
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
    })

    const left = makeMap(splitLeftRef.current)
    const middle = splitMode === 'three' ? makeMap(splitMiddleRef.current!) : null
    const right = makeMap(splitRightRef.current)

    splitLeftMapRef.current = left
    splitMiddleMapRef.current = middle
    splitRightMapRef.current = right

    const allMaps = [left, middle, right].filter((m): m is maplibregl.Map => m !== null)
    allMaps.forEach((m) => m.addControl(new maplibregl.NavigationControl(), 'top-right'))

    let syncing = false
    const syncFrom = (source: maplibregl.Map) => () => {
      if (syncing) return
      syncing = true
      allMaps.filter((m) => m !== source).forEach((m) => m.jumpTo({ center: source.getCenter(), zoom: source.getZoom() }))
      syncing = false
    }
    allMaps.forEach((m) => m.on('move', syncFrom(m)))
    left.on('moveend', () => setMapBounds(readBounds(left)))

    // In two-pane: left = current, right = forecast
    // In three-pane: left = past, middle = current, right = forecast
    const currentMap = splitMode === 'three' ? middle! : left
    const pastMap = splitMode === 'three' ? left : null

    if (pastMap) {
      pastMap.on('load', () => {
        api.currentStatus(pastYear, pastWeek).then((rows) => addStatusLayer(pastMap, 'split-past', rows)).catch(() => undefined)
      })
    }

    currentMap.on('load', () => {
      api.currentStatus().then((rows) => addStatusLayer(currentMap, 'split-current', rows)).catch(() => undefined)
      setMapBounds(readBounds(currentMap))
    })
    right.on('load', () => {
      api.forecastStatus(forecastYear, forecastWeek)
        .then((rows) => addStatusLayer(right, 'split-forecast', rows))
        .catch(() => undefined)
    })

    return () => {
      allMaps.forEach((m) => m.remove())
      splitLeftMapRef.current = null
      splitMiddleMapRef.current = null
      splitRightMapRef.current = null
    }
  }, [splitMode])

  // Refresh forecast layer when quarter/year changes
  useEffect(() => {
    const right = splitRightMapRef.current
    if (!splitActive || !right) return
    api
      .forecastStatus(forecastYear, forecastWeek)
      .then((rows) => addStatusLayer(right, 'split-forecast', rows))
      .catch(() => undefined)
  }, [forecastYear, forecastWeek, splitActive])

  // Refresh past layer when past year/week changes
  useEffect(() => {
    const pastMap = splitMode === 'three' ? splitLeftMapRef.current : null
    if (!pastMap) return
    api.currentStatus(pastYear, pastWeek)
      .then((rows) => addStatusLayer(pastMap, 'split-past', rows))
      .catch(() => undefined)
  }, [pastYear, pastWeek, splitMode])

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

  // Past stats — only relevant in triple split mode
  useEffect(() => {
    if (!mapBounds || splitMode !== 'three') return
    api
      .mapStats(mapBounds, pastYear, pastWeek)
      .then(setPastStats)
      .catch(() => setPastStats(null))
  }, [mapBounds, splitMode, pastYear, pastWeek])

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
        cameras: cctvCameras,
        offsets: offsets.length > 0 ? offsets : [5],
      })
      setCctvResult(result)
      setCctvStatus(`${result.candidate_cctv.features.length} candidate camera position(s) found`)
    } catch (e) {
      setCctvStatus(e instanceof Error ? e.message : 'CCTV pipeline failed — check that uploaded files are valid GeoJSON')
    }
  }

  // Map click handler for Bitcoin power-check: clicks on plotted site circles only
  useEffect(() => {
    const map = mapRef.current
    if (!map || !btcPickMode) return
    const canvas = map.getCanvas()
    const setCursor = () => { canvas.style.cursor = 'crosshair' }
    const unsetCursor = () => { canvas.style.cursor = '' }
    setCursor()
    function handleClick(e: maplibregl.MapMouseEvent) {
      // Only register clicks on actual site markers, not empty map
      const features = map.queryRenderedFeatures(e.point, { layers: ['current-status-point'] })
      if (!features.length) return
      const props = features[0].properties as { site_id: string }
      const row = currentStatusRows.find((r) => r.site_id === props.site_id)
      if (!row || row.latitude == null || row.longitude == null) return
      const site = { site_id: row.site_id, lat: row.latitude, lng: row.longitude }
      setBtcSites((prev) => {
        if (prev.length >= btcMode) return prev
        if (prev.some((s) => s.site_id === site.site_id)) return prev
        const next = [...prev, site]
        if (next.length >= btcMode) setBtcPickMode(false)
        return next
      })
    }
    map.on('click', handleClick)
    return () => {
      map.off('click', handleClick)
      unsetCursor()
    }
  }, [btcPickMode, btcMode, currentStatusRows])

  // Draw selected sites + connecting line/polygon + centroid + buffer on map
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    // Haversine in km
    function hav(lat1: number, lon1: number, lat2: number, lon2: number) {
      const R = 6371, dLat = (lat2 - lat1) * Math.PI / 180, dLon = (lon2 - lon1) * Math.PI / 180
      const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2
      return R * 2 * Math.asin(Math.sqrt(a))
    }
    // Approximate circle polygon (64 pts), radius in km
    function circlePolygon(lat: number, lng: number, radiusKm: number): [number, number][] {
      const coords: [number, number][] = []
      for (let i = 0; i <= 64; i++) {
        const a = (i / 64) * 2 * Math.PI
        const dLat = (radiusKm / 6371) * (180 / Math.PI) * Math.cos(a)
        const dLng = (radiusKm / 6371) * (180 / Math.PI) * Math.sin(a) / Math.cos(lat * Math.PI / 180)
        coords.push([lng + dLng, lat + dLat])
      }
      return coords
    }

    const apply = () => {
      // Site pin highlights
      const pinData: FeatureCollection = {
        type: 'FeatureCollection',
        features: btcSites.map((s) => ({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [s.lng, s.lat] },
          properties: { site_id: s.site_id },
        })),
      }
      const pinSrc = map.getSource('btc-pins') as maplibregl.GeoJSONSource | undefined
      if (pinSrc) { pinSrc.setData(pinData) } else {
        map.addSource('btc-pins', { type: 'geojson', data: pinData })
        map.addLayer({ id: 'btc-pins-ring', type: 'circle', source: 'btc-pins', paint: { 'circle-radius': 11, 'circle-color': 'transparent', 'circle-stroke-width': 3, 'circle-stroke-color': '#f59e0b' } })
      }

      if (btcSites.length < 2) {
        // Clear geometry layers when < 2 sites
        const empty: FeatureCollection = { type: 'FeatureCollection', features: [] };
        ['btc-line', 'btc-buffer', 'btc-centroid'].forEach((id) => {
          const src = map.getSource(id) as maplibregl.GeoJSONSource | undefined
          if (src) src.setData(empty)
        })
        return
      }

      const cLat = btcSites.reduce((s, p) => s + p.lat, 0) / btcSites.length
      const cLng = btcSites.reduce((s, p) => s + p.lng, 0) / btcSites.length
      const maxDistKm = Math.max(...btcSites.map((s) => hav(s.lat, s.lng, cLat, cLng)))
      const bufferKm = Math.max(maxDistKm, 0.1) // min 100m

      // Line (2 sites) or filled polygon (3 sites)
      const lineCoords = btcSites.map((s) => [s.lng, s.lat])
      const lineData: FeatureCollection = {
        type: 'FeatureCollection',
        features: [{
          type: 'Feature',
          geometry: btcSites.length === 2
            ? { type: 'LineString', coordinates: lineCoords }
            : { type: 'Polygon', coordinates: [[...lineCoords, lineCoords[0]]] },
          properties: {},
        }],
      }
      const lineSrc = map.getSource('btc-line') as maplibregl.GeoJSONSource | undefined
      if (lineSrc) { lineSrc.setData(lineData) } else {
        map.addSource('btc-line', { type: 'geojson', data: lineData })
        map.addLayer({ id: 'btc-line-fill', type: 'fill', source: 'btc-line', filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': '#eab308', 'fill-opacity': 0.06 } })
        map.addLayer({ id: 'btc-line-stroke', type: 'line', source: 'btc-line', paint: { 'line-color': '#eab308', 'line-width': 2, 'line-dasharray': [6, 4] } })
      }

      // Buffer circle
      const bufData: FeatureCollection = {
        type: 'FeatureCollection',
        features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: [circlePolygon(cLat, cLng, bufferKm)] }, properties: {} }],
      }
      const bufSrc = map.getSource('btc-buffer') as maplibregl.GeoJSONSource | undefined
      if (bufSrc) { bufSrc.setData(bufData) } else {
        map.addSource('btc-buffer', { type: 'geojson', data: bufData })
        map.addLayer({ id: 'btc-buffer-fill', type: 'fill', source: 'btc-buffer', paint: { 'fill-color': '#16a34a', 'fill-opacity': 0.06 } })
        map.addLayer({ id: 'btc-buffer-line', type: 'line', source: 'btc-buffer', paint: { 'line-color': '#16a34a', 'line-width': 1.5, 'line-dasharray': [4, 4] } })
      }

      // Centroid diamond marker
      const centData: FeatureCollection = {
        type: 'FeatureCollection',
        features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [cLng, cLat] }, properties: {} }],
      }
      const centSrc = map.getSource('btc-centroid') as maplibregl.GeoJSONSource | undefined
      if (centSrc) { centSrc.setData(centData) } else {
        map.addSource('btc-centroid', { type: 'geojson', data: centData })
        map.addLayer({ id: 'btc-centroid-circle', type: 'circle', source: 'btc-centroid', paint: { 'circle-radius': 7, 'circle-color': '#16a34a', 'circle-stroke-width': 2.5, 'circle-stroke-color': '#fff' } })
      }
    }
    if (map.isStyleLoaded()) apply(); else map.once('load', apply)
  }, [btcSites])

  // Illegal power-draw check: centroid + max-dist buffer → query GeoServer layers
  async function runBtcAnalysis() {
    if (btcSites.length < btcMode) {
      setBtcStatus(`Select ${btcMode} sites first`)
      return
    }
    if (!fixedLayers) {
      setBtcStatus('GeoServer layer configuration not loaded yet')
      return
    }
    setBtcResult(null)
    setBtcStatus('Querying nearby buildings and substations…')
    const cLat = btcSites.reduce((s, p) => s + p.lat, 0) / btcSites.length
    const cLng = btcSites.reduce((s, p) => s + p.lng, 0) / btcSites.length
    const maxDistM = Math.max(...btcSites.map((s) => haversineDistanceMeters([cLng, cLat], [s.lng, s.lat])))
    const radiusM = Math.max(maxDistM, 100)
    try {
      const [buildings, substations] = await Promise.all([
        api.nearbyGeoserverFeatures(fixedLayers.buildings_layer, cLat, cLng, radiusM),
        api.nearbyGeoserverFeatures(fixedLayers.substations_layer, cLat, cLng, radiusM * 3),
      ])
      const subsWithDist = substations
        .map((sub) => ({ name: sub.name, distM: haversineDistanceMeters([cLng, cLat], [sub.lng, sub.lat]) }))
        .sort((a, b) => a.distM - b.distM)
      setBtcResult({ buildingCount: buildings.length, radiusKm: radiusM / 1000, substations: subsWithDist.slice(0, 5) })
      setBtcStatus(
        buildings.length === 0 && substations.length === 0
          ? `No data on layers "${fixedLayers.buildings_layer}"/"${fixedLayers.substations_layer}" — publish them in GeoServer`
          : `${buildings.length} flagged building(s) within ${fmtDistance(radiusM)} of centroid`,
      )
      const map = mapRef.current
      if (map) {
        const plotData: FeatureCollection = {
          type: 'FeatureCollection',
          features: buildings.map((b) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [b.lng, b.lat] }, properties: {} })),
        }
        const apply = () => {
          const existing = map.getSource('btc-buildings') as maplibregl.GeoJSONSource | undefined
          if (existing) { existing.setData(plotData) } else {
            map.addSource('btc-buildings', { type: 'geojson', data: plotData })
            map.addLayer({ id: 'btc-buildings-circle', type: 'circle', source: 'btc-buildings', paint: { 'circle-radius': 5, 'circle-color': '#dc2626', 'circle-stroke-width': 1.5, 'circle-stroke-color': '#fff' } })
          }
        }
        if (map.isStyleLoaded()) apply(); else map.once('load', apply)
      }
    } catch (e) {
      setBtcStatus(e instanceof Error ? e.message : 'Power-draw check failed')
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

  // Plot CCTV pipeline layers on map and zoom to AOI when result arrives
  useEffect(() => {
    const map = mapRef.current
    if (!map || !cctvResult) return
    const apply = () => {
      const layerDefs: { id: string; src: GeoJSON.FeatureCollection; type: 'fill' | 'line' | 'circle'; color: string; opacity: number }[] = [
        { id: 'cctv-aoi', src: cctvResult.aoi, type: 'fill', color: '#60a5fa', opacity: 0.07 },
        { id: 'cctv-buildings', src: cctvResult.dissolved_buildings, type: 'fill', color: '#a78bfa', opacity: 0.25 },
        { id: 'cctv-surv', src: cctvResult.surv_area, type: 'fill', color: '#4ade80', opacity: 0.07 },
        { id: 'cctv-hex', src: cctvResult.hex_grid, type: 'line', color: '#818cf8', opacity: 0.4 },
        { id: 'cctv-wedge', src: cctvResult.wedge, type: 'fill', color: '#f97316', opacity: 0.25 },
        { id: 'cctv-candidates', src: cctvResult.cand_cctv_clean, type: 'circle', color: '#f97316', opacity: 1 },
      ]
      for (const { id, src, type, color, opacity } of layerDefs) {
        const existing = map.getSource(id) as maplibregl.GeoJSONSource | undefined
        if (existing) { existing.setData(src); continue }
        map.addSource(id, { type: 'geojson', data: src })
        if (type === 'fill') map.addLayer({ id, type: 'fill', source: id, paint: { 'fill-color': color, 'fill-opacity': opacity } })
        else if (type === 'line') map.addLayer({ id, type: 'line', source: id, paint: { 'line-color': color, 'line-width': 1, 'line-opacity': opacity } })
        else map.addLayer({ id, type: 'circle', source: id, paint: { 'circle-radius': 5, 'circle-color': color, 'circle-stroke-width': 1.5, 'circle-stroke-color': '#fff' } })
      }
      // Zoom to AOI bounding box
      const coords: [number, number][] = []
      const collectCoords = (geom: GeoJSON.Geometry) => {
        if (geom.type === 'Polygon') geom.coordinates.flat().forEach(([x, y]) => coords.push([x, y]))
        else if (geom.type === 'MultiPolygon') geom.coordinates.flat(2).forEach(([x, y]) => coords.push([x, y]))
      }
      cctvResult.aoi.features.forEach((f) => f.geometry && collectCoords(f.geometry as GeoJSON.Geometry))
      if (coords.length > 0) {
        const lngs = coords.map(([x]) => x), lats = coords.map(([, y]) => y)
        map.fitBounds([[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]], { padding: 60, duration: 800 })
      }
    }
    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)
  }, [cctvResult])

  return (
    <div className="flex items-stretch gap-4">
    <div className="min-w-0 flex-1 space-y-4">
      <GlassPanel className="relative z-30 flex flex-wrap items-center gap-3">
        {/* View mode icons: single / two-pane / three-pane */}
        <div className="flex items-center gap-1 rounded-xl border border-white/15 p-1">
          {([
            { mode: 'none' as const, title: 'Single map',
              icon: <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="18" rx="2"/></svg> },
            { mode: 'two' as const, title: 'Split: Current vs Forecast',
              icon: <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="9" height="18" rx="1.5"/><rect x="13" y="3" width="9" height="18" rx="1.5"/></svg> },
            { mode: 'three' as const, title: 'Split: Past vs Current vs Forecast',
              icon: <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="1" y="3" width="6" height="18" rx="1.5"/><rect x="9" y="3" width="6" height="18" rx="1.5"/><rect x="17" y="3" width="6" height="18" rx="1.5"/></svg> },
          ] as const).map(({ mode, title, icon }) => (
            <button
              key={mode}
              title={title}
              onClick={() => setSplitMode(mode)}
              className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${
                splitMode === mode ? 'bg-sky-400 text-ink-900' : 'text-white/60 hover:text-white'
              }`}
            >
              {icon}
            </button>
          ))}
        </div>

        {/* Timeline filter — always visible; label changes by mode */}
        {!splitActive && availableWeeks.length > 0 && (
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40">Week</span>
            <select
              value={mapFilterKey}
              onChange={(e) => {
                setMapFilterKey(e.target.value)
                const f = parseKey(e.target.value)
                const map = mapRef.current
                if (!map) return
                api.currentStatus(f?.year, f?.week).then((rows) => {
                  setCurrentStatusRows(rows)
                  addStatusLayer(map, 'current-status', rows)
                }).catch(() => undefined)
              }}
              className="rounded-xl border border-white/20 bg-ink-900 px-2.5 py-1.5 text-xs text-white/80 focus:border-sky-400/60 focus:outline-none"
            >
              <option value="latest">Latest</option>
              {availableWeeks.map(({ year, week }) => (
                <option key={`${year}-${week}`} value={`${year}-${week}`}>
                  {year} W{String(week).padStart(2, '0')}
                </option>
              ))}
            </select>
          </div>
        )}

        {splitMode === 'three' && availableWeeks.length > 0 && (
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40">Past</span>
            <select
              value={pastKey}
              onChange={(e) => setPastKey(e.target.value)}
              className="rounded-xl border border-white/20 bg-ink-900 px-2.5 py-1.5 text-xs text-white/80 focus:border-sky-400/60 focus:outline-none"
            >
              {availableWeeks.map(({ year, week }) => (
                <option key={`${year}-${week}`} value={`${year}-${week}`}>
                  {year} W{String(week).padStart(2, '0')}
                </option>
              ))}
            </select>
          </div>
        )}

        {splitActive && (
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40">Forecast</span>
            <input type="number" value={forecastYear} onChange={(e) => setForecastYear(Number(e.target.value))}
              className="w-16 rounded-xl border border-white/20 bg-ink-900 px-2.5 py-1.5 text-xs text-white/80 focus:border-sky-400/60 focus:outline-none" />
            <div className="flex gap-0.5 rounded-xl border border-white/20 bg-ink-900 p-0.5">
              {QUARTER_WEEKS.map((w, i) => (
                <button key={w} onClick={() => setForecastWeek(w)}
                  className={`rounded-lg px-2 py-1 text-[10px] font-semibold transition-colors ${forecastWeek === w ? 'bg-accent-400 text-ink-900' : 'text-white/55 hover:text-white'}`}>
                  Q{i + 1}
                </button>
              ))}
            </div>
          </div>
        )}

        {!splitActive && (
          <>
            <div className="relative z-30">
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
            {tool !== 'none' && (
              <button
                onClick={() => { setTool('none'); setDraftPoints([]) }}
                className="h-9 rounded-xl border border-white/20 px-3 text-xs font-semibold text-white/70"
              >
                Cancel draw
              </button>
            )}

            <div>
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

            <button
              onClick={() => setToolDrawer((v) => (v === 'genset' ? 'none' : 'genset'))}
              title="Genset/substation routing"
              className={`flex h-9 w-9 items-center justify-center rounded-xl border text-white/80 ${toolDrawer === 'genset' ? 'border-amber-400/60 bg-amber-400/10' : 'border-white/20'}`}
            >
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M13 2 3 14h7l-1 8 11-12h-7l1-8z" />
              </svg>
            </button>

            <button
              onClick={() => setToolDrawer((v) => (v === 'cctv' ? 'none' : 'cctv'))}
              title="CCTV camera planning"
              className={`flex h-9 w-9 items-center justify-center rounded-xl border text-white/80 ${toolDrawer === 'cctv' ? 'border-emerald-400/60 bg-emerald-400/10' : 'border-white/20'}`}
            >
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="7" width="13" height="10" rx="2" />
                <path d="M16 10.5 21 7v10l-5-3.5" />
              </svg>
            </button>

            <button
              onClick={() => setToolDrawer((v) => (v === 'bitcoin' ? 'none' : 'bitcoin'))}
              title="Unauthorized power-draw check"
              className={`flex h-9 w-9 items-center justify-center rounded-xl border text-white/80 ${toolDrawer === 'bitcoin' ? 'border-sky-400/60 bg-sky-400/10' : 'border-white/20'}`}
            >
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="9" />
                <path d="M9.5 9h2l-1 3h2l-2.5 4M14.5 9h-1" />
              </svg>
            </button>
            {(tool === 'line' || tool === 'polygon') && (
              <button
                onClick={finishDraft}
                className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-ink-900"
              >
                Finish ({draftPoints.length} pts)
              </button>
            )}

            {/* Far-right zone: measure results and Genset single-site panel */}
            <div className="ml-auto flex items-center gap-3">
              {measureActive && (
                <button
                  onClick={() => setMeasurePoints([])}
                  className="h-9 rounded-xl border border-white/20 px-3 text-xs font-semibold text-white/70"
                >
                  Clear points
                </button>
              )}
              {measurePoints.length >= 2 && (
                <div className="flex h-9 items-center rounded-xl border border-sky-400/30 bg-sky-400/10 px-3 text-xs">
                  <span className="text-white/55">Total distance </span>
                  <span className="ml-1 font-semibold text-sky-300">
                    {fmtDistance(measurePoints.slice(1).reduce((sum, p, i) => sum + haversineDistanceMeters(measurePoints[i], p), 0))}
                  </span>
                </div>
              )}


            </div>
          </>
        )}

        {status && <p className="text-sm text-white/70">{status}</p>}
      </GlassPanel>

      <div className={`grid gap-4 ${splitActive ? '' : 'lg:grid-cols-[1fr_280px]'}`}>
        {!splitActive && (
          <div className="relative h-[55vh] w-full">
            <div ref={containerRef} className="h-full w-full overflow-hidden rounded-3xl border border-white/15" />

            {/* Layers — controls: base map mode + which layers are on.
                Top-left. */}
            <div className="absolute left-3 top-3 z-10">
              <button
                onClick={() => setLayersOpen((v) => !v)}
                title="Layers"
                className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/20 bg-ink-950 text-white/80"
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
                </svg>
              </button>

              {layersOpen && (
                <div className="mt-2 max-h-[48vh] w-64 overflow-y-auto rounded-2xl border border-white/20 bg-ink-950 p-3 text-xs text-white/85 shadow-[0_8px_32px_-8px_rgba(0,0,0,0.8)]">
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
                <div className="mb-2 max-h-[40vh] w-56 overflow-y-auto rounded-2xl border border-white/20 bg-ink-950 p-3 text-xs text-white/85 shadow-[0_8px_32px_-8px_rgba(0,0,0,0.8)]">
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
                className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/20 bg-ink-950 text-white/80"
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 6h16M4 12h10M4 18h7" />
                </svg>
              </button>
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

      {splitActive && (
        <div className={`grid h-[70vh] gap-3 ${splitMode === 'three' ? 'grid-cols-3' : 'grid-cols-2'}`}>
          {splitMode === 'three' && (
            <div className="relative overflow-hidden rounded-3xl border border-white/15">
              <div className="absolute left-2 top-2 z-10 rounded-lg bg-ink-950 px-2.5 py-1 text-xs font-semibold text-white/90">
                Past ({pastKey ? pastKey.replace('-', ' W') : '—'})
              </div>
              <div ref={splitLeftRef} className="h-full w-full" />
            </div>
          )}
          <div className="relative overflow-hidden rounded-3xl border border-white/15">
            <div className="absolute left-2 top-2 z-10 rounded-lg bg-ink-950 px-2.5 py-1 text-xs font-semibold text-white/90">
              {splitMode === 'three' ? 'Current' : 'Current status'}
            </div>
            <div ref={splitMode === 'three' ? splitMiddleRef : splitLeftRef} className="h-full w-full" />
          </div>
          <div className="relative overflow-hidden rounded-3xl border border-white/15">
            <div className="absolute left-2 top-2 z-10 rounded-lg bg-ink-950 px-2.5 py-1 text-xs font-semibold text-white/90">
              Forecast ({forecastYear} Q{QUARTER_WEEKS.indexOf(forecastWeek) + 1})
            </div>
            <div ref={splitRightRef} className="h-full w-full" />
          </div>
        </div>
      )}

      {!splitActive && <MapStatsPanel title="Viewport stats" stats={currentStats} />}

      {splitActive && (
        <div className={`grid gap-4 ${splitMode === 'three' ? 'grid-cols-3' : 'grid-cols-2'}`}>
          {splitMode === 'three' && (
            <MapStatsPanel title="Viewport stats — past" stats={pastStats} compact />
          )}
          <MapStatsPanel title="Viewport stats — current" stats={currentStats} compact />
          <MapStatsPanel title="Viewport stats — forecast" stats={forecastStats} compact />
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

    </div>{/* end inner content column */}

    {/* ── Tool panel — in-flow right column, no overlap ── */}
    {toolDrawer !== 'none' && (
      <GlassPanel className="flex w-80 shrink-0 flex-col overflow-hidden !p-0">
          {/* Panel header */}
          <div className="flex shrink-0 items-center justify-between border-b border-white/10 px-4 py-3">
            <p className="font-display text-sm font-semibold">
              {toolDrawer === 'genset' && 'Genset / Substation routing'}
              {toolDrawer === 'cctv' && 'CCTV camera planning'}
              {toolDrawer === 'bitcoin' && 'Unauthorized power-draw check'}
            </p>
            <button
              onClick={() => setToolDrawer('none')}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-white/40 hover:bg-white/10 hover:text-white"
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M6 6l12 12M18 6 6 18" />
              </svg>
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-4">

            {/* ── GENSET ── */}
            {toolDrawer === 'genset' && (
              <div className="space-y-4">
                {/* Pricing inputs */}
                <div>
                  <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/45">Cable pricing</p>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="mb-1 block text-[10px] text-white/45">Material (RM/100m)</label>
                      <input
                        type="number"
                        value={matPer100m}
                        onChange={(e) => setMatPer100m(Number(e.target.value))}
                        className="w-full rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs focus:border-sky-400/60 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-[10px] text-white/45">Engineering (RM/100m)</label>
                      <input
                        type="number"
                        value={engPer100m}
                        onChange={(e) => setEngPer100m(Number(e.target.value))}
                        className="w-full rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs focus:border-sky-400/60 focus:outline-none"
                      />
                    </div>
                  </div>
                </div>

                {/* Tab switcher: Single / Bulk */}
                <div className="flex rounded-xl border border-white/15 bg-white/5 p-0.5">
                  {(['single', 'bulk'] as const).map((t) => (
                    <button
                      key={t}
                      onClick={() => setGensetTab(t)}
                      className={`flex-1 rounded-lg py-1.5 text-xs font-semibold transition-colors ${
                        gensetTab === t ? 'bg-white/15 text-white' : 'text-white/50 hover:text-white/80'
                      }`}
                    >
                      {t === 'single' ? 'Single site' : 'Bulk (xlsx/csv)'}
                    </button>
                  ))}
                </div>

                {/* Single site */}
                {gensetTab === 'single' && (
                  <div className="space-y-2">
                    <div className="flex gap-1.5">
                      <button
                        onClick={() => { setGensetPickMode((v) => !v); setGensetPickedLatLng(null) }}
                        className={`flex-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold ${
                          gensetPickMode ? 'bg-sky-400 text-ink-900' : 'border border-white/20 text-white/70'
                        }`}
                      >
                        {gensetPickMode ? 'Click a point on map…' : 'Pick point on map'}
                      </button>
                      {gensetPickedLatLng && (
                        <button onClick={() => setGensetPickedLatLng(null)} className="rounded-lg border border-white/20 px-2.5 py-1.5 text-xs text-white/60">
                          Clear
                        </button>
                      )}
                    </div>
                    {gensetPickedLatLng ? (
                      <p className="rounded-lg bg-white/5 px-2.5 py-1.5 text-xs text-white/60">
                        Pinned: {gensetPickedLatLng[0].toFixed(5)}, {gensetPickedLatLng[1].toFixed(5)}
                      </p>
                    ) : (
                      <input
                        value={gensetSiteId}
                        onChange={(e) => setGensetSiteId(e.target.value)}
                        placeholder="Or search by site ID — e.g. N00377"
                        className="w-full rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs focus:border-sky-400/60 focus:outline-none"
                      />
                    )}
                    <button
                      onClick={runGenset}
                      className="w-full rounded-lg bg-gradient-to-r from-accent-400 to-accent-500 px-3 py-2 text-xs font-semibold text-ink-900"
                    >
                      Find route
                    </button>
                    {gensetStatus && <p className="text-[11px] text-white/60">{gensetStatus}</p>}
                    {gensetResult && gensetResult.results.length > 0 && (
                      <div className="space-y-1.5">
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-white/45">
                          {gensetResult.results.length} route{gensetResult.results.length !== 1 ? 's' : ''}
                        </p>
                        {gensetResult.results.map((r, i) => {
                          const units = r.road_dist_m / 100
                          const matCost = Math.round(units * matPer100m)
                          const engCost = Math.round(units * engPer100m)
                          const total = matCost + engCost
                          return (
                            <button
                              key={r.osm_id}
                              onClick={() => mapRef.current?.flyTo({ center: [r.lng, r.lat], zoom: 14, duration: 800 })}
                              className="flex w-full flex-col rounded-lg bg-white/5 px-2.5 py-2 text-left hover:bg-white/10"
                            >
                              <div className="mb-1 flex w-full items-center justify-between">
                                <span className="text-xs font-semibold text-sky-300">{i === 0 ? '★ ' : ''}{r.name}</span>
                                <span className="text-xs font-semibold text-accent-400">{r.road_dist_km} km</span>
                              </div>
                              <div className="grid grid-cols-3 gap-1 text-[10px] text-white/45">
                                <span>Material <span className="text-white/70">RM {matCost.toLocaleString()}</span></span>
                                <span>Eng. <span className="text-white/70">RM {engCost.toLocaleString()}</span></span>
                                <span>Total <span className="font-semibold text-emerald-300">RM {total.toLocaleString()}</span></span>
                              </div>
                            </button>
                          )
                        })}
                        {/* Summary card — shortest route */}
                        {(() => {
                          const r = gensetResult.results[0]
                          const units = r.road_dist_m / 100
                          const mat = Math.round(units * matPer100m)
                          const eng = Math.round(units * engPer100m)
                          return (
                            <div className="rounded-lg border border-accent-400/25 bg-accent-400/8 px-2.5 py-2 text-xs">
                              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/45">Shortest route summary</p>
                              <div className="flex justify-between"><span className="text-white/55">Distance</span><span className="font-semibold">{r.road_dist_km} km</span></div>
                              <div className="flex justify-between"><span className="text-white/55">Material</span><span>RM {mat.toLocaleString()}</span></div>
                              <div className="flex justify-between"><span className="text-white/55">Engineering</span><span>RM {eng.toLocaleString()}</span></div>
                              <div className="mt-1 flex justify-between border-t border-white/10 pt-1"><span className="font-semibold text-white/55">Total</span><span className="font-semibold text-accent-400">RM {(mat + eng).toLocaleString()}</span></div>
                            </div>
                          )
                        })()}
                      </div>
                    )}
                  </div>
                )}

                {/* Bulk mode */}
                {gensetTab === 'bulk' && (
                  <div className="space-y-2">
                    <p className="text-[10px] text-white/45">Substations from {fixedLayers ? `"${fixedLayers.substations_layer}"` : 'GeoServer'}</p>
                    <div>
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
                    {gensetStatus && <p className="text-[11px] text-white/60">{gensetStatus}</p>}
                    {gensetBulkResults.length > 0 && (
                      <div className="max-h-48 overflow-y-auto rounded-xl bg-white/5">
                        <table className="w-full text-left text-xs">
                          <thead className="sticky top-0 bg-ink-900/95 text-white/45">
                            <tr>
                              <th className="px-2.5 py-1.5">Site</th>
                              <th className="px-2.5 py-1.5">Nearest sub</th>
                              <th className="px-2.5 py-1.5">km</th>
                              <th className="px-2.5 py-1.5">Total RM</th>
                            </tr>
                          </thead>
                          <tbody>
                            {gensetBulkResults.map((r) => {
                              const best = r.result?.results[0]
                              const units = best ? best.road_dist_m / 100 : 0
                              const total = best ? Math.round(units * (matPer100m + engPer100m)) : 0
                              return (
                                <tr key={r.siteId} className="border-t border-white/5">
                                  <td className="px-2.5 py-1.5 font-semibold">{r.siteId}</td>
                                  <td className="px-2.5 py-1.5 text-white/70">{best ? best.name : r.error ?? '—'}</td>
                                  <td className="px-2.5 py-1.5 text-white/70">{best ? best.road_dist_km : '—'}</td>
                                  <td className="px-2.5 py-1.5 text-emerald-300">{best ? total.toLocaleString() : '—'}</td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                    <div className="flex gap-2">
                      <button
                        onClick={runGensetBulk}
                        className="flex-1 rounded-lg bg-gradient-to-r from-accent-400 to-accent-500 px-3 py-2 text-xs font-semibold text-ink-900"
                      >
                        Process file
                      </button>
                      {gensetBulkResults.length > 0 && (
                        <button
                          onClick={() => {
                            const rows = ['Site ID,Nearest Substation,Road Distance (km),Material RM,Engineering RM,Total RM,Error']
                            for (const r of gensetBulkResults) {
                              const best = r.result?.results[0]
                              if (best) {
                                const units = best.road_dist_m / 100
                                const mat = Math.round(units * matPer100m)
                                const eng = Math.round(units * engPer100m)
                                rows.push(`${r.siteId},"${best.name}",${best.road_dist_km},${mat},${eng},${mat + eng},`)
                              } else {
                                rows.push(`${r.siteId},,,,,${r.error ?? ''}`)
                              }
                            }
                            const blob = new Blob([rows.join('\n')], { type: 'text/csv' })
                            const a = document.createElement('a')
                            a.href = URL.createObjectURL(blob)
                            a.download = 'genset_routes.csv'
                            a.click()
                          }}
                          className="rounded-lg border border-emerald-400/40 bg-emerald-400/10 px-3 py-2 text-xs font-semibold text-emerald-300"
                        >
                          Export CSV
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── CCTV ── */}
            {toolDrawer === 'cctv' && (
              <div className="space-y-4">
                {/* GeoJSON file uploads */}
                {([
                  ['Building footprints (GeoJSON)', cctvBuildingFile, setCctvBuildingFile, 'cctv-building-input2'],
                  ['Parking areas (GeoJSON)', cctvParkingFile, setCctvParkingFile, 'cctv-parking-input2'],
                  ['Existing poles (GeoJSON)', cctvPolesFile, setCctvPolesFile, 'cctv-poles-input2'],
                ] as const).map(([label, file, setFile, inputId]) => (
                  <div key={label}>
                    <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">{label}</label>
                    <input id={inputId} type="file" accept=".geojson,.json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="hidden" />
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

                {/* Camera specs table */}
                <div>
                  <div className="mb-1.5 flex items-center justify-between">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-white/45">Camera specs</p>
                    <button
                      onClick={() => setCctvCameras((prev) => [...prev, { camera_type: `Type ${String.fromCharCode(65 + prev.length)}`, hfov_deg: 90, range_m: 30, unit_price_rm: 500 }])}
                      className="rounded-lg border border-white/20 px-2 py-0.5 text-[10px] text-white/60 hover:bg-white/10"
                    >
                      + Add
                    </button>
                  </div>
                  <div className="overflow-x-auto rounded-xl border border-white/10">
                    <table className="w-full text-left text-[11px]">
                      <thead className="bg-white/5 text-[10px] text-white/45">
                        <tr>
                          <th className="px-2 py-1.5">Type</th>
                          <th className="px-2 py-1.5">HFoV°</th>
                          <th className="px-2 py-1.5">Range m</th>
                          <th className="px-2 py-1.5">RM</th>
                          <th className="px-2 py-1.5" />
                        </tr>
                      </thead>
                      <tbody>
                        {cctvCameras.map((cam, i) => (
                          <tr key={i} className="border-t border-white/8">
                            <td className="px-1.5 py-1">
                              <input value={cam.camera_type} onChange={(e) => setCctvCameras((prev) => prev.map((c, j) => j === i ? { ...c, camera_type: e.target.value } : c))}
                                className="w-16 rounded bg-white/5 px-1.5 py-0.5 text-[11px] focus:outline-none focus:ring-1 focus:ring-sky-400/50" />
                            </td>
                            <td className="px-1.5 py-1">
                              <input type="number" value={cam.hfov_deg} onChange={(e) => setCctvCameras((prev) => prev.map((c, j) => j === i ? { ...c, hfov_deg: Number(e.target.value) } : c))}
                                className="w-12 rounded bg-white/5 px-1.5 py-0.5 text-[11px] focus:outline-none focus:ring-1 focus:ring-sky-400/50" />
                            </td>
                            <td className="px-1.5 py-1">
                              <input type="number" value={cam.range_m} onChange={(e) => setCctvCameras((prev) => prev.map((c, j) => j === i ? { ...c, range_m: Number(e.target.value) } : c))}
                                className="w-12 rounded bg-white/5 px-1.5 py-0.5 text-[11px] focus:outline-none focus:ring-1 focus:ring-sky-400/50" />
                            </td>
                            <td className="px-1.5 py-1">
                              <input type="number" value={cam.unit_price_rm} onChange={(e) => setCctvCameras((prev) => prev.map((c, j) => j === i ? { ...c, unit_price_rm: Number(e.target.value) } : c))}
                                className="w-16 rounded bg-white/5 px-1.5 py-0.5 text-[11px] focus:outline-none focus:ring-1 focus:ring-sky-400/50" />
                            </td>
                            <td className="px-1.5 py-1">
                              {cctvCameras.length > 1 && (
                                <button onClick={() => setCctvCameras((prev) => prev.filter((_, j) => j !== i))} className="text-white/30 hover:text-red-400">×</button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Offsets */}
                <div>
                  <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/45">Setback offsets (m, comma-separated)</label>
                  <input
                    value={cctvOffsets}
                    onChange={(e) => setCctvOffsets(e.target.value)}
                    className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-xs focus:border-sky-400/60 focus:outline-none"
                  />
                </div>

                {cctvStatus && <p className="text-xs text-white/60">{cctvStatus}</p>}

                {cctvResult && cctvResult.camera_cost_summary.features.length > 0 && (
                  <div>
                    <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-white/45">Results</p>
                    <ul className="space-y-1 text-xs">
                      {cctvResult.camera_cost_summary.features.map((f, i) => (
                        <li key={i} className="rounded-lg bg-white/5 px-2.5 py-1.5">
                          <span className="font-semibold">{String(f.properties?.camera_type)}</span>
                          <span className="text-white/55"> — {String(f.properties?.count)}× — {fmtCurrency(Number(f.properties?.total_cost_rm))}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <button
                  onClick={runCctv}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 py-2.5 text-sm font-semibold text-white hover:bg-emerald-400"
                >
                  <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
                  Run CCTV Pipeline
                </button>
              </div>
            )}

            {/* ── POWER CHECK / BITCOIN ── */}
            {toolDrawer === 'bitcoin' && (() => {
              const SLOT_COLORS = ['#2563eb', '#f59e0b', '#7c3aed']
              const searchResults = btcSearch.length >= 2
                ? currentStatusRows.filter((r) => r.site_id.toLowerCase().includes(btcSearch.toLowerCase())).slice(0, 8)
                : []
              return (
                <div className="space-y-4">
                  <p className="text-xs text-white/55">
                    Select {btcMode === 2 ? '2 sites to draw a line and find the midpoint' : '3 sites to draw a polygon and find the centroid'}. The buffer radius equals the max distance from the centroid to a selected site.
                  </p>

                  {/* Mode toggle */}
                  <div>
                    <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-white/45">Mode</p>
                    <div className="flex rounded-xl border border-white/15 bg-white/5 p-0.5">
                      {([2, 3] as const).map((m) => (
                        <button key={m} onClick={() => { setBtcMode(m); setBtcSites([]); setBtcResult(null); setBtcStatus(null) }}
                          className={`flex-1 rounded-lg py-1.5 text-xs font-semibold transition-colors ${btcMode === m ? 'bg-white/15 text-white' : 'text-white/50 hover:text-white/80'}`}>
                          {m === 2 ? '2-site (line)' : '3-site (polygon)'}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Search */}
                  <div className="relative">
                    <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-white/45">Search site</p>
                    <input
                      value={btcSearch}
                      onChange={(e) => setBtcSearch(e.target.value)}
                      placeholder="Site ID — e.g. N00377"
                      className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-xs focus:border-sky-400/60 focus:outline-none"
                    />
                    {searchResults.length > 0 && (
                      <div className="absolute left-0 right-0 top-full z-10 mt-1 overflow-hidden rounded-xl border border-white/15 bg-ink-900/98 shadow-xl">
                        {searchResults.map((r) => (
                          <button
                            key={r.site_id}
                            onClick={() => {
                              if (r.latitude == null || r.longitude == null) return
                              const site = { site_id: r.site_id, lat: r.latitude, lng: r.longitude }
                              setBtcSites((prev) => {
                                if (prev.length >= btcMode || prev.some((s) => s.site_id === r.site_id)) return prev
                                return [...prev, site]
                              })
                              setBtcSearch('')
                            }}
                            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-white/10"
                          >
                            <span className="font-semibold text-sky-300">{r.site_id}</span>
                            <span className="text-white/45">{r.region}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Site slots */}
                  <div>
                    <div className="mb-1.5 flex items-center justify-between">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-white/45">Selected sites</p>
                      {btcSites.length > 0 && (
                        <button onClick={() => { setBtcSites([]); setBtcResult(null); setBtcStatus(null); setBtcPickMode(false) }}
                          className="text-[10px] text-white/40 hover:text-red-400">Reset</button>
                      )}
                    </div>
                    <div className="space-y-1.5">
                      {Array.from({ length: btcMode }).map((_, i) => {
                        const s = btcSites[i]
                        const col = SLOT_COLORS[i]
                        return (
                          <div key={i} className="flex items-center gap-2 rounded-lg border px-2.5 py-2 text-xs transition-colors"
                            style={{ borderColor: s ? col : 'rgba(255,255,255,0.1)', background: s ? col + '10' : 'transparent' }}>
                            <div className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: s ? col : 'transparent', border: `2px solid ${col}` }} />
                            {s ? (
                              <>
                                <span className="flex-1 font-semibold" style={{ color: col }}>{s.site_id}</span>
                                <span className="text-white/45">{s.lat.toFixed(4)}, {s.lng.toFixed(4)}</span>
                                <button onClick={() => setBtcSites((prev) => prev.filter((_, j) => j !== i))}
                                  className="ml-1 text-white/30 hover:text-red-400">✕</button>
                              </>
                            ) : (
                              <span className="flex-1 italic text-white/35">Site {i + 1}</span>
                            )}
                          </div>
                        )
                      })}
                    </div>
                    {btcSites.length < btcMode && (
                      <button
                        onClick={() => setBtcPickMode((v) => !v)}
                        className={`mt-2 w-full rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                          btcPickMode ? 'bg-amber-400 text-ink-900' : 'border border-white/20 text-white/70 hover:bg-white/10'
                        }`}
                      >
                        {btcPickMode ? `Click a site on the map…` : `+ Click map to add site ${btcSites.length + 1}`}
                      </button>
                    )}
                  </div>

                  {btcSites.length >= btcMode && (
                    <button onClick={runBtcAnalysis}
                      className="w-full rounded-xl bg-gradient-to-r from-sky-500 to-accent-500 py-2.5 text-xs font-semibold text-white">
                      Run analysis
                    </button>
                  )}

                  {btcStatus && <p className="text-[11px] text-white/60">{btcStatus}</p>}

                  {btcResult && (
                    <div className="space-y-1.5 rounded-xl border border-white/10 bg-white/5 p-3 text-xs">
                      <div className="flex justify-between">
                        <span className="text-white/55">Buffer radius</span>
                        <span className="font-semibold">{fmtDistance(btcResult.radiusKm * 1000)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-white/55">Flagged buildings</span>
                        <span className={`font-semibold ${btcResult.buildingCount > 0 ? 'text-red-300' : ''}`}>{btcResult.buildingCount}</span>
                      </div>
                      {btcResult.substations.length > 0 && (
                        <div className="mt-2 border-t border-white/10 pt-2">
                          <p className="mb-1 text-[10px] text-white/45">Nearest substations</p>
                          {btcResult.substations.map((s, i) => (
                            <div key={i} className="flex justify-between text-[11px]">
                              <span className="truncate text-white/70">{s.name || 'Substation'}</span>
                              <span className="ml-2 shrink-0 text-amber-300">{fmtDistance(s.distM)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })()}
          </div>
        </GlassPanel>
      )}

    {forecastModal && (
      <ForecastModal
        siteId={forecastModal.siteId}
        rows={forecastModal.rows}
        onClose={() => setForecastModal(null)}
      />
    )}
  </div>
  )
}
