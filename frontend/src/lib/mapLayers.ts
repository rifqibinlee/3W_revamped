import type { FeatureCollection, Geometry } from 'geojson'
import maplibregl from 'maplibre-gl'
import { api, type CurrentStatusRow, type SiteDetail } from './api'

// Flattens every coordinate pair out of any GeoJSON geometry type —
// used to fit the map to a shape regardless of whether it's a Point,
// LineString, or Polygon. (A prior version only handled the Point
// case and fell back to a hardcoded default center otherwise, so a
// drawn polygon/line annotation would "not show up": the map jumped
// to an unrelated location at deep zoom instead of panning to the
// shape that was actually drawn.)
function flattenCoordinates(geometry: Geometry): [number, number][] {
  switch (geometry.type) {
    case 'Point':
      return [geometry.coordinates as [number, number]]
    case 'LineString':
    case 'MultiPoint':
      return geometry.coordinates as [number, number][]
    case 'Polygon':
    case 'MultiLineString':
      return (geometry.coordinates as [number, number][][]).flat()
    case 'MultiPolygon':
      return (geometry.coordinates as [number, number][][][]).flat(2)
    case 'GeometryCollection':
      return geometry.geometries.flatMap(flattenCoordinates)
    default:
      return []
  }
}

// Fits the map to every annotation's geometry (not just the first
// one), falling back to a single default-centered view when there's
// nothing to show yet.
export function fitMapToAnnotations(
  map: maplibregl.Map,
  annotations: { geometry: unknown }[],
  defaultCenter: [number, number],
) {
  const allCoords = annotations.flatMap((a) => flattenCoordinates(a.geometry as Geometry))
  if (allCoords.length === 0) {
    map.jumpTo({ center: defaultCenter, zoom: 11 })
    return
  }
  if (allCoords.length === 1) {
    map.jumpTo({ center: allCoords[0], zoom: 14 })
    return
  }
  const bounds = allCoords.reduce(
    (b, c) => b.extend(c),
    new maplibregl.LngLatBounds(allCoords[0], allCoords[0]),
  )
  map.fitBounds(bounds, { padding: 60, maxZoom: 16, duration: 0 })
}

// Covers the real site distribution (lat 1.3-6.2, lng 101.6-104.3) —
// used by the Notes/Projects embedded maps to show coverage holes
// network-wide rather than scoped to a moving viewport like the Map
// page does.
const NETWORK_BOUNDS = { south: 1.0, west: 101.0, north: 6.5, east: 104.6 }

const SIGNAL_BAND_COLORS = { high: '#facc15', mid: '#f97316', low: '#dc2626' } as const

// Network-wide coverage holes (MR/Ookla weak-signal points) — empty
// until real MR/Ookla source files are ingested (none exist in
// dataset_example), wired correctly so it lights up the moment that
// data exists, same as the Map page's Signal layers.
export async function addCoverageHolesLayer(map: maplibregl.Map, sourceId = 'embedded-coverage-holes') {
  const bands: Array<'high' | 'mid' | 'low'> = ['high', 'mid', 'low']
  const results = await Promise.all(bands.map((band) => api.coverageHolesByBand(NETWORK_BOUNDS, band).catch(() => [])))
  const data: FeatureCollection = {
    type: 'FeatureCollection',
    features: bands.flatMap((band, i) =>
      results[i].map((r) => ({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: [r.longitude, r.latitude] },
        properties: { band },
      })),
    ),
  }
  const existing = map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined
  if (existing) {
    existing.setData(data)
    return
  }
  map.addSource(sourceId, { type: 'geojson', data })
  map.addLayer({
    id: `${sourceId}-circle`,
    type: 'circle',
    source: sourceId,
    paint: {
      'circle-radius': 4,
      'circle-color': ['match', ['get', 'band'], 'high', SIGNAL_BAND_COLORS.high, 'mid', SIGNAL_BAND_COLORS.mid, SIGNAL_BAND_COLORS.low],
    },
  })
}

// Shared between the Map page and the small embedded maps on Notes/
// Projects — those used to point at the bare demotiles vector style
// (no roads/rivers/labels at all) and never rendered any site
// markers, so they looked broken/empty. CartoDB Voyager is a free,
// no-API-key raster basemap with roads/water/labels.
//
// A function, not a shared object constant: MapLibre's Map constructor
// mutates the style spec object it's given (it normalizes/freezes
// parts of it), so three pages all passing the exact same object
// reference to their own `new maplibregl.Map()` caused the second and
// third instances to silently fail to render — each page needs its
// own fresh copy.
export function getBaseStyle(): maplibregl.StyleSpecification {
  return {
    version: 8,
    sources: {
      'carto-voyager': {
        type: 'raster',
        tiles: ['https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png'],
        tileSize: 256,
        attribution: '© OpenStreetMap contributors © CARTO',
      },
    },
    layers: [{ id: 'carto-voyager-layer', type: 'raster', source: 'carto-voyager' }],
  }
}

// Esri satellite imagery + a CartoDB label-only overlay, as a single
// combined style — same stack the Map page's "Satellite" mode uses,
// but baked into one style spec for pages (Notes/Projects) that don't
// have a Layers panel to toggle between base modes.
export function getSatelliteStyle(): maplibregl.StyleSpecification {
  return {
    version: 8,
    sources: {
      'satellite-base': {
        type: 'raster',
        tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
        tileSize: 256,
        attribution: 'Esri',
      },
      'satellite-labels': {
        type: 'raster',
        tiles: ['https://a.basemaps.cartocdn.com/rastertiles/light_only_labels/{z}/{x}/{y}@2x.png'],
        tileSize: 256,
        attribution: '© OpenStreetMap contributors © CARTO',
      },
    },
    layers: [
      { id: 'satellite-base-layer', type: 'raster', source: 'satellite-base' },
      { id: 'satellite-labels-layer', type: 'raster', source: 'satellite-labels' },
    ],
  }
}

export function fmt(n: number | null | undefined, digits = 1): string {
  return n == null || Number.isNaN(n) ? '—' : n.toFixed(digits)
}

export function statusGeoJson(rows: CurrentStatusRow[]): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: rows
      .filter((r) => r.latitude != null && r.longitude != null)
      .map((r) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [r.longitude as number, r.latitude as number] },
        properties: { site_id: r.site_id, region: r.region, congested: r.congested, congestedFlag: r.congested ? 1 : 0 },
      })),
  }
}

// Drives the RING color (not the fill — the fill stays neutral glass
// white) so the cluster reads as "frosted glass with a status ring"
// rather than a flat colored blob, matching GlassPanel's actual look
// (white/8 fill, white/20 border, soft shadow) instead of inventing a
// different visual language just for clusters.
const CONGESTED_RATIO_COLOR: maplibregl.ExpressionSpecification = [
  'interpolate', ['linear'], ['/', ['get', 'congestedSum'], ['get', 'point_count']],
  0, '#60a5fa', 0.5, '#c084fc', 1, '#f87171',
]

// Healthy and congested sites cluster together in one group (separate
// groups used to overlap and visually compete at the same spot). The
// glass look is three circle layers per cluster: a soft white glow
// underneath (stands in for GlassPanel's drop shadow), a translucent
// white glass disc, and a colored ring on top whose color reflects
// what fraction of the cluster is congested (via clusterProperties
// summing a 0/1 flag during clustering) — status lives in the ring,
// not the fill, so the glass stays glass.
export function addStatusLayer(map: maplibregl.Map, sourceId: string, rows: CurrentStatusRow[], onSiteClick?: (siteId: string) => void) {
  const data = statusGeoJson(rows)

  const existing = map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined
  if (existing) {
    existing.setData(data)
    return
  }

  map.addSource(sourceId, {
    type: 'geojson', data, cluster: true, clusterMaxZoom: 14, clusterRadius: 60,
    clusterProperties: { congestedSum: ['+', ['get', 'congestedFlag']] },
  })

  map.addLayer({
    id: `${sourceId}-cluster-glow`,
    type: 'circle',
    source: sourceId,
    filter: ['has', 'point_count'],
    paint: {
      'circle-radius': ['step', ['get', 'point_count'], 22, 25, 28, 100, 36],
      'circle-color': '#ffffff',
      'circle-opacity': 0.18,
      'circle-blur': 1,
    },
  })
  map.addLayer({
    id: `${sourceId}-cluster-circle`,
    type: 'circle',
    source: sourceId,
    filter: ['has', 'point_count'],
    paint: {
      'circle-radius': ['step', ['get', 'point_count'], 16, 25, 20, 100, 26],
      'circle-color': '#ffffff',
      'circle-opacity': 0.14,
      'circle-stroke-width': 2,
      'circle-stroke-color': CONGESTED_RATIO_COLOR,
      'circle-stroke-opacity': 0.9,
    },
  })
  map.addLayer({
    id: `${sourceId}-cluster-count`,
    type: 'symbol',
    source: sourceId,
    filter: ['has', 'point_count'],
    layout: { 'text-field': '{point_count_abbreviated}', 'text-size': 12, 'text-font': ['Open Sans Bold'] },
    paint: { 'text-color': '#ffffff', 'text-halo-color': 'rgba(15,15,30,0.6)', 'text-halo-width': 1 },
  })
  map.addLayer({
    id: `${sourceId}-point`,
    type: 'circle',
    source: sourceId,
    filter: ['!', ['has', 'point_count']],
    paint: {
      'circle-radius': 6,
      'circle-color': '#ffffff',
      'circle-opacity': 0.18,
      'circle-stroke-width': 2,
      'circle-stroke-color': ['case', ['get', 'congested'], '#f87171', '#60a5fa'],
      'circle-stroke-opacity': 0.95,
    },
  })

  map.on('mouseenter', `${sourceId}-cluster-circle`, () => (map.getCanvas().style.cursor = 'pointer'))
  map.on('mouseleave', `${sourceId}-cluster-circle`, () => (map.getCanvas().style.cursor = ''))
  map.on('mouseenter', `${sourceId}-point`, () => (map.getCanvas().style.cursor = 'pointer'))
  map.on('mouseleave', `${sourceId}-point`, () => (map.getCanvas().style.cursor = ''))

  map.on('click', `${sourceId}-cluster-circle`, (e) => {
    const f = e.features?.[0]
    if (!f) return
    const clusterId = (f.properties as { cluster_id: number }).cluster_id
    const source = map.getSource(sourceId) as maplibregl.GeoJSONSource
    source.getClusterExpansionZoom(clusterId).then((zoom) => {
      map.easeTo({ center: (f.geometry as GeoJSON.Point).coordinates as [number, number], zoom })
    })
  })

  map.on('click', `${sourceId}-point`, (e) => {
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

// Switches visible tab inside a site-detail popup. Called from inline
// onclick attributes in the popup HTML — must be on window so the
// MapLibre-injected markup can reach it.
if (typeof window !== 'undefined') {
  ;(window as unknown as Record<string, unknown>).swPopupTab = (pid: string, tab: string) => {
    const tabs = ['kpi', 'forecast', 'upgrade', 'capex']
    for (const t of tabs) {
      const panel = document.getElementById(`${pid}-${t}`)
      const btn = document.getElementById(`${pid}-btn-${t}`)
      const active = t === tab
      if (panel) panel.style.display = active ? 'block' : 'none'
      if (btn) btn.classList.toggle('active', active)
    }
  }
}

// Renders a small SVG line chart for an array of (label, value) points.
// Used inline in popup HTML — no React, no external deps.
function sparklineSvg(
  points: { label: string; value: number; alert?: boolean }[],
  opts: { width?: number; height?: number; color?: string; alertColor?: string; maxHint?: number; unit?: string },
): string {
  const W = opts.width ?? 300
  const H = opts.height ?? 80
  const pad = { top: 8, right: 8, bottom: 24, left: 30 }
  const innerW = W - pad.left - pad.right
  const innerH = H - pad.top - pad.bottom

  const vals = points.map((p) => p.value)
  const min = 0
  const max = Math.max(opts.maxHint ?? 0, ...vals) * 1.1 || 1

  const x = (i: number) => pad.left + (i / Math.max(points.length - 1, 1)) * innerW
  const y = (v: number) => pad.top + innerH - ((v - min) / (max - min)) * innerH

  const linePts = points.map((p, i) => `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')
  const fillPts = [
    `${x(0).toFixed(1)},${(pad.top + innerH).toFixed(1)}`,
    ...points.map((p, i) => `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`),
    `${x(points.length - 1).toFixed(1)},${(pad.top + innerH).toFixed(1)}`,
  ].join(' ')

  const color = opts.color ?? '#6e9fff'
  const alertColor = opts.alertColor ?? '#f87171'

  const dots = points
    .map((p, i) => {
      const c = p.alert ? alertColor : color
      return `<circle cx="${x(i).toFixed(1)}" cy="${y(p.value).toFixed(1)}" r="2.5" fill="${c}"/>`
    })
    .join('')

  const xLabels = points
    .filter((_, i) => i === 0 || i === points.length - 1 || points.length <= 6 || i % Math.ceil(points.length / 5) === 0)
    .map((p) => {
      const i = points.indexOf(p)
      return `<text x="${x(i).toFixed(1)}" y="${H - 4}" text-anchor="${i === 0 ? 'start' : i === points.length - 1 ? 'end' : 'middle'}" font-size="8" fill="rgba(255,255,255,0.35)">${p.label}</text>`
    })
    .join('')

  // y-axis ticks (top + mid)
  const yTicks = [max, max / 2].map((v) => {
    const yy = y(v).toFixed(1)
    return `<line x1="${pad.left - 3}" y1="${yy}" x2="${W - pad.right}" y2="${yy}" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
            <text x="${pad.left - 5}" y="${(parseFloat(yy) + 3).toFixed(1)}" text-anchor="end" font-size="8" fill="rgba(255,255,255,0.3)">${v.toFixed(0)}${opts.unit ?? ''}</text>`
  }).join('')

  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">
    ${yTicks}
    <polygon points="${fillPts}" fill="${color}" fill-opacity="0.08"/>
    <polyline points="${linePts}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>
    ${dots}
    ${xLabels}
  </svg>`
}

export function siteDetailHtml(siteId: string, detail: SiteDetail | null, loading: boolean): string {
  const pid = `sw_${siteId.replace(/[^a-zA-Z0-9]/g, '_')}`

  if (loading) {
    return `<div style="padding:16px 20px;color:rgba(255,255,255,0.6);font-size:13px;">
      <strong style="color:#fff;font-size:14px;">${siteId}</strong><br/>
      <span style="opacity:.6;margin-top:4px;display:block;">Loading…</span>
    </div>`
  }
  if (!detail) {
    return `<div style="padding:16px 20px;color:rgba(255,255,255,0.6);font-size:13px;">
      <strong style="color:#fff;font-size:14px;">${siteId}</strong><br/>
      <span style="opacity:.5;margin-top:4px;display:block;">No data available</span>
    </div>`
  }

  const congested = detail.congested
  const headerGradient = congested
    ? 'linear-gradient(135deg,#7f1d1d,#991b1b)'
    : 'linear-gradient(135deg,#1e1b4b,#1e3a5f)'
  const statusBadge = congested
    ? '<span class="sw-badge sw-badge-congested">⚠ Congested</span>'
    : '<span class="sw-badge sw-badge-healthy">✓ Healthy</span>'

  const region = detail.site?.region ?? '—'
  const cluster = detail.site?.cluster ?? '—'

  // ── KPI tab ──────────────────────────────────────────────────────────────
  const kpiRows = detail.sectors.length
    ? detail.sectors.map((s) => {
        const prbAlert = s.eric_prb_util_rate >= 80 ? 'sw-popup-td-alert' : ''
        const thptAlert = s.eric_dl_user_ip_thpt > 0 && s.eric_dl_user_ip_thpt < 5 ? 'sw-popup-td-alert' : ''
        const sectorLabel = s.zoom_sector_id.split('_').pop() ?? s.zoom_sector_id
        return `<tr>
          <td title="${s.zoom_sector_id}">Sec ${sectorLabel}</td>
          <td>${s.f1f2f3 ?? '—'}</td>
          <td class="${prbAlert}">${fmt(s.eric_prb_util_rate)}%</td>
          <td class="${thptAlert}">${fmt(s.eric_dl_user_ip_thpt)}</td>
          <td>${fmt(s.eric_data_volume_ul_dl)}</td>
          <td>${fmt(s.eric_max_rrc_user, 0)}</td>
        </tr>`
      }).join('')
    : `<tr><td colspan="6" style="text-align:center;opacity:.45;padding:12px;">No sector KPIs available</td></tr>`

  const kpiPanel = `
    <div style="overflow-x:auto;">
      <table class="sw-popup-table">
        <thead><tr>
          <th>Sector</th><th>Carrier</th><th>PRB%</th><th>Thpt</th><th>Vol</th><th>Users</th>
        </tr></thead>
        <tbody>${kpiRows}</tbody>
      </table>
    </div>`

  // ── Forecast tab — SVG sparkline charts ──────────────────────────────────
  const forecastSlice = detail.forecast.slice(0, 13)
  let forecastPanel: string

  if (forecastSlice.length === 0) {
    forecastPanel = `<div style="padding:20px;text-align:center;opacity:.45;font-size:12px;">No forecast data available</div>`
  } else {
    const prbPoints = forecastSlice.map((f) => ({
      label: `W${f.week}`,
      value: f.predicted_eric_prb_util_rate,
      alert: f.congested,
    }))
    const thptPoints = forecastSlice.map((f) => ({
      label: `W${f.week}`,
      value: f.predicted_eric_dl_user_ip_thpt,
      alert: f.predicted_eric_dl_user_ip_thpt > 0 && f.predicted_eric_dl_user_ip_thpt < 5,
    }))
    const volPoints = forecastSlice.map((f) => ({
      label: `W${f.week}`,
      value: f.predicted_eric_data_volume_ul_dl,
      alert: false,
    }))

    const prbChart = sparklineSvg(prbPoints, { color: '#6e9fff', alertColor: '#f87171', maxHint: 100, unit: '%' })
    const thptChart = sparklineSvg(thptPoints, { color: '#4ade80', alertColor: '#f87171' })
    const volChart = sparklineSvg(volPoints, { color: '#c084fc' })

    // Congestion status row
    const statusDots = forecastSlice.map((f) => {
      const c = f.congested ? '#f87171' : '#4ade80'
      const label = `Wk ${f.week}`
      return `<div title="${label}: ${f.congested ? 'Congested' : 'Normal'}" style="width:10px;height:10px;border-radius:50%;background:${c};flex-shrink:0;"></div>`
    }).join('')

    forecastPanel = `
      <div style="padding:10px 14px 4px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;color:rgba(255,255,255,0.4);">PRB Utilization (%)</div>
          <button onclick="window.swOpenForecastModal && window.swOpenForecastModal('${siteId}')"
            style="background:rgba(110,159,255,0.15);border:1px solid rgba(110,159,255,0.3);color:#6e9fff;font-size:10px;font-weight:700;padding:4px 10px;border-radius:6px;cursor:pointer;letter-spacing:0.03em;">
            ▶ Full Forecast
          </button>
        </div>
        ${prbChart}
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;color:rgba(255,255,255,0.4);margin:10px 0 6px;">DL Throughput (Mbps)</div>
        ${thptChart}
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;color:rgba(255,255,255,0.4);margin:10px 0 6px;">Data Volume (GB)</div>
        ${volChart}
        <div style="margin-top:10px;">
          <div style="font-size:10px;color:rgba(255,255,255,0.4);margin-bottom:5px;">Weekly congestion outlook</div>
          <div style="display:flex;gap:4px;flex-wrap:wrap;">${statusDots}</div>
          <div style="display:flex;gap:12px;margin-top:5px;">
            <div style="display:flex;align-items:center;gap:4px;font-size:10px;color:rgba(255,255,255,0.45);"><div style="width:8px;height:8px;border-radius:50%;background:#4ade80;"></div>Normal</div>
            <div style="display:flex;align-items:center;gap:4px;font-size:10px;color:rgba(255,255,255,0.45);"><div style="width:8px;height:8px;border-radius:50%;background:#f87171;"></div>Congested</div>
          </div>
        </div>
      </div>`
  }

  // ── Upgrade tab — two band matrices (current vs suggested) ───────────────
  // Bands and carriers that the CAPEX solver tracks (F3/MOCN not in dataset).
  const BANDS = ['L9', 'L18', 'L21', 'L26'] as const
  const CARRIERS = ['F1', 'F2'] as const

  type CarrierKey = (typeof CARRIERS)[number]

  interface CapexRow extends Record<string, unknown> {
    zoom_sector_id: string
    suggested_upgrade_case: string
    estimated_total_capex_rm: number
    projected_prb_pct: number
  }

  const upgradePanel = (() => {
    if (!detail.capex_upgrades.length) {
      return `<div style="padding:20px;text-align:center;opacity:.45;font-size:12px;">No upgrade data available</div>`
    }

    const upgrades = detail.capex_upgrades as CapexRow[]

    const buildMatrix = (type: 'current' | 'suggested') => {
      const carrierColors: Record<CarrierKey, { bg: string; text: string; border: string }> = {
        F1: { bg: 'rgba(234,179,8,0.08)',  text: 'rgba(253,224,71,0.7)',  border: 'rgba(234,179,8,0.2)' },
        F2: { bg: 'rgba(59,130,246,0.08)', text: 'rgba(147,197,253,0.7)', border: 'rgba(59,130,246,0.2)' },
      }

      const headerCells = CARRIERS.map((c) =>
        BANDS.map((b, i) => {
          const isLast = i === BANDS.length - 1
          const col = carrierColors[c]
          return `<th style="background:${col.bg};color:${col.text};text-align:center;padding:4px 2px;font-size:9px;border-right:1px solid ${isLast ? col.border : 'rgba(255,255,255,0.06)'};">${b}</th>`
        }).join('')
      ).join('')

      const bodyRows = upgrades.map((u) => {
        const sec = String(u.zoom_sector_id).split('_').pop() ?? u.zoom_sector_id
        const prbPct = Number(u.projected_prb_pct)
        const prbAlert = prbPct > 73

        const cells = CARRIERS.map((c) =>
          BANDS.map((b, i) => {
            const isLast = i === BANDS.length - 1
            const key = `${type}_${c.toLowerCase()}_${b.toLowerCase()}`
            const val = u[key] ?? '—'
            const otherKey = `${type === 'current' ? 'suggested' : 'current'}_${c.toLowerCase()}_${b.toLowerCase()}`
            const otherVal = u[otherKey] ?? '—'
            const changed = String(val) !== String(otherVal) && String(otherVal) !== '—'
            const borderRight = isLast
              ? `border-right:1px solid rgba(255,255,255,0.12);`
              : `border-right:1px solid rgba(255,255,255,0.06);`
            const highlight =
              changed && type === 'current'
                ? 'background:rgba(248,113,113,0.12);color:#f87171;font-weight:700;'
                : changed && type === 'suggested'
                  ? 'background:rgba(74,222,128,0.12);color:#4ade80;font-weight:700;'
                  : 'color:rgba(255,255,255,0.7);'
            return `<td style="text-align:center;padding:4px 2px;font-size:10px;${borderRight}${highlight}">${val}</td>`
          }).join('')
        ).join('')

        const extraCols = type === 'suggested'
          ? `<td style="text-align:center;padding:4px 6px;font-size:10px;font-weight:700;${prbAlert ? 'color:#f87171;' : 'color:#4ade80;'}">${prbPct.toFixed(1)}%</td>
             <td style="text-align:center;padding:4px 6px;font-size:9px;color:rgba(255,255,255,0.6);">${u.suggested_upgrade_case || '—'}</td>`
          : ''

        return `<tr style="border-bottom:1px solid rgba(255,255,255,0.06);">
          <td style="padding:4px 8px;font-size:10px;font-weight:700;color:#6e9fff;border-right:1px solid rgba(255,255,255,0.12);">Sec ${sec}</td>
          ${cells}${extraCols}
        </tr>`
      }).join('')

      const extraHeaders = type === 'suggested'
        ? `<th style="background:rgba(255,255,255,0.06);color:rgba(255,255,255,0.45);text-align:center;padding:4px 4px;font-size:9px;border-left:1px solid rgba(255,255,255,0.1);">Cap%</th>
           <th style="background:rgba(255,255,255,0.06);color:rgba(255,255,255,0.45);text-align:center;padding:4px 4px;font-size:9px;">Case</th>`
        : ''

      const carrierGroupHeaders = CARRIERS.map((c) => {
        const col = carrierColors[c]
        return `<th colspan="${BANDS.length}" style="background:${col.bg};color:${col.text};text-align:center;padding:5px 4px;font-size:10px;font-weight:700;border-right:1px solid ${col.border};">${c}</th>`
      }).join('')

      return `
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;color:rgba(255,255,255,0.4);padding:10px 14px 6px;">
          ${type === 'current' ? '▶ Current Configuration' : '▲ Recommended Upgrade'}
        </div>
        <div style="overflow-x:auto;padding:0 10px 8px;">
          <table style="width:100%;border-collapse:collapse;font-size:10px;">
            <thead>
              <tr>
                <th style="background:rgba(255,255,255,0.04);color:rgba(255,255,255,0.4);padding:5px 8px;font-size:9px;text-align:left;border-right:1px solid rgba(255,255,255,0.12);">Sec</th>
                ${carrierGroupHeaders}${type === 'suggested' ? `<th colspan="2" style="background:rgba(255,255,255,0.04);color:rgba(255,255,255,0.4);padding:5px 4px;font-size:9px;border-left:1px solid rgba(255,255,255,0.1);">Result</th>` : ''}
              </tr>
              <tr>
                <th style="border-right:1px solid rgba(255,255,255,0.12);"></th>
                ${headerCells}${extraHeaders}
              </tr>
            </thead>
            <tbody>${bodyRows}</tbody>
          </table>
        </div>`
    }

    const hasCongestion = upgrades.some((u) => Number(u.projected_prb_pct) > 73 || u.suggested_upgrade_case)

    return `
      ${buildMatrix('current')}
      <div style="height:1px;background:rgba(255,255,255,0.08);margin:2px 0;"></div>
      ${hasCongestion
        ? buildMatrix('suggested')
        : `<div style="padding:12px 14px;font-size:11px;font-weight:700;color:#4ade80;">✓ Capacity healthy — no upgrade required</div>`
      }`
  })()

  // ── CAPEX tab — per-sector EQ / ES / Total breakdown + site total ─────────
  const capexPanel = (() => {
    if (!detail.capex_upgrades.length) {
      return `<div style="padding:20px;text-align:center;opacity:.45;font-size:12px;">No CAPEX data available</div>`
    }
    const upgrades = detail.capex_upgrades as Array<Record<string, unknown>>
    const totalCapex = upgrades.reduce((s, u) => s + (Number(u.estimated_total_capex_rm) || 0), 0)
    const eqTotal   = upgrades.reduce((s, u) => s + (Number(u.eq_capex_rm) || 0), 0)
    const esTotal   = upgrades.reduce((s, u) => s + (Number(u.es_capex_rm) || 0), 0)

    const rows = upgrades.map((u) => {
      const sec  = String(u.zoom_sector_id ?? '').split('_').pop() ?? u.zoom_sector_id
      const eq   = Number(u.eq_capex_rm) || 0
      const es   = Number(u.es_capex_rm) || 0
      const tot  = Number(u.estimated_total_capex_rm) || 0
      const cas  = String(u.suggested_upgrade_case ?? '—')
      return `<tr style="border-bottom:1px solid rgba(255,255,255,0.06);">
        <td style="padding:6px 10px;font-size:11px;font-weight:700;color:#6e9fff;">Sec ${sec}</td>
        <td style="padding:6px 8px;font-size:11px;color:rgba(255,255,255,0.7);text-align:right;">RM ${fmt(eq, 0)}</td>
        <td style="padding:6px 8px;font-size:11px;color:rgba(255,255,255,0.7);text-align:right;">RM ${fmt(es, 0)}</td>
        <td style="padding:6px 10px;font-size:11px;font-weight:700;color:#ffd23f;text-align:right;">RM ${fmt(tot, 0)}</td>
        <td style="padding:6px 10px;font-size:10px;color:rgba(255,255,255,0.45);max-width:140px;">${cas}</td>
      </tr>`
    }).join('')

    return `
      <div style="margin:10px 12px 6px;padding:12px 14px;border-radius:10px;background:linear-gradient(135deg,rgba(255,210,63,0.1),rgba(255,210,63,0.04));border:1px solid rgba(255,210,63,0.2);display:flex;justify-content:space-between;align-items:center;">
        <div>
          <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:rgba(255,255,255,0.4);">Total Site CAPEX</div>
          <div style="font-size:22px;font-weight:800;color:#ffd23f;margin-top:2px;">RM ${fmt(totalCapex, 0)}</div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:10px;color:rgba(255,255,255,0.4);">Equipment (EQ)</div>
          <div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.8);">RM ${fmt(eqTotal, 0)}</div>
          <div style="font-size:10px;color:rgba(255,255,255,0.4);margin-top:4px;">Engineering (ES)</div>
          <div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.8);">RM ${fmt(esTotal, 0)}</div>
        </div>
      </div>
      <div style="overflow-x:auto;padding:0 12px 12px;">
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.1);">
              <th style="padding:5px 10px;font-size:10px;font-weight:700;text-transform:uppercase;color:rgba(255,255,255,0.4);text-align:left;">Sector</th>
              <th style="padding:5px 8px;font-size:10px;font-weight:700;text-transform:uppercase;color:rgba(255,255,255,0.4);text-align:right;">EQ</th>
              <th style="padding:5px 8px;font-size:10px;font-weight:700;text-transform:uppercase;color:rgba(255,255,255,0.4);text-align:right;">ES</th>
              <th style="padding:5px 10px;font-size:10px;font-weight:700;text-transform:uppercase;color:rgba(255,255,255,0.4);text-align:right;">Total</th>
              <th style="padding:5px 10px;font-size:10px;font-weight:700;text-transform:uppercase;color:rgba(255,255,255,0.4);">Case</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`
  })()

  return `
    <div>
      <div style="background:${headerGradient};padding:14px 18px 12px;flex-shrink:0;">
        <div style="font-size:16px;font-weight:800;letter-spacing:0.3px;color:#fff;">${siteId}</div>
        <div style="font-size:11px;color:rgba(255,255,255,0.55);margin-top:2px;margin-bottom:8px;">${cluster} · ${region}</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
          ${statusBadge}
          <span class="sw-badge sw-badge-neutral">${region}</span>
        </div>
      </div>

      <div class="sw-popup-tabs" style="flex-shrink:0;">
        <button id="${pid}-btn-kpi"      class="sw-popup-tab active"  onclick="window.swPopupTab('${pid}','kpi')">KPIs</button>
        <button id="${pid}-btn-forecast" class="sw-popup-tab"         onclick="window.swPopupTab('${pid}','forecast')">Forecast</button>
        <button id="${pid}-btn-upgrade"  class="sw-popup-tab"         onclick="window.swPopupTab('${pid}','upgrade')">Upgrade</button>
        <button id="${pid}-btn-capex"    class="sw-popup-tab"         onclick="window.swPopupTab('${pid}','capex')">CAPEX</button>
      </div>

      <div class="sw-popup-scrollable">
        <div id="${pid}-kpi">                              ${kpiPanel}      </div>
        <div id="${pid}-forecast" style="display:none;">  ${forecastPanel} </div>
        <div id="${pid}-upgrade"  style="display:none;">  ${upgradePanel}  </div>
        <div id="${pid}-capex"    style="display:none;">  ${capexPanel}    </div>
      </div>
    </div>`
}
