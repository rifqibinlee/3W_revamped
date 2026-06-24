import type { FeatureCollection } from 'geojson'
import maplibregl from 'maplibre-gl'
import { api, type CurrentStatusRow, type SiteDetail } from './api'

// Shared between the Map page and the small embedded maps on Notes/
// Projects — those used to point at the bare demotiles vector style
// (no roads/rivers/labels at all) and never rendered any site
// markers, so they looked broken/empty. CartoDB Voyager is a free,
// no-API-key raster basemap with roads/water/labels.
export const BASE_STYLE: maplibregl.StyleSpecification = {
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

const CONGESTED_RATIO_COLOR: maplibregl.ExpressionSpecification = [
  'interpolate', ['linear'], ['/', ['get', 'congestedSum'], ['get', 'point_count']],
  0, '#3b82f6', 0.5, '#a855f7', 1, '#dc2626',
]

// Healthy and congested sites cluster together in one group (separate
// groups used to overlap and visually compete at the same spot) — the
// cluster bubble's color is a blue→red gradient driven by what
// fraction of the cluster is congested, via clusterProperties summing
// a 0/1 "congested" flag during clustering. The "glassy" look is two
// circle layers: a soft blurred halo underneath, a crisper translucent
// disc with a white rim on top.
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
      'circle-radius': ['step', ['get', 'point_count'], 24, 25, 30, 100, 38],
      'circle-color': CONGESTED_RATIO_COLOR,
      'circle-opacity': 0.35,
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
      'circle-color': CONGESTED_RATIO_COLOR,
      'circle-opacity': 0.55,
      'circle-stroke-width': 1.5,
      'circle-stroke-color': 'rgba(255,255,255,0.75)',
    },
  })
  map.addLayer({
    id: `${sourceId}-cluster-count`,
    type: 'symbol',
    source: sourceId,
    filter: ['has', 'point_count'],
    layout: { 'text-field': '{point_count_abbreviated}', 'text-size': 12, 'text-font': ['Open Sans Bold'] },
    paint: { 'text-color': '#ffffff' },
  })
  map.addLayer({
    id: `${sourceId}-point`,
    type: 'circle',
    source: sourceId,
    filter: ['!', ['has', 'point_count']],
    paint: {
      'circle-radius': 6,
      'circle-color': ['case', ['get', 'congested'], '#dc2626', '#3b82f6'],
      'circle-opacity': 0.7,
      'circle-stroke-width': 1.5,
      'circle-stroke-color': 'rgba(255,255,255,0.75)',
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
