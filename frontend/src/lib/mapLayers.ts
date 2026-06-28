import type { FeatureCollection } from 'geojson'
import maplibregl from 'maplibre-gl'
import { api, type CurrentStatusRow, type SiteDetail } from './api'

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

export function siteDetailHtml(siteId: string, detail: SiteDetail | null, loading: boolean): string {
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
