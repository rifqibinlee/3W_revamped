import type { ForecastRow } from '../lib/api'

interface Props {
  siteId: string
  rows: ForecastRow[]
  onClose: () => void
}

// Groups forecast rows by sector, returns sorted sector ids.
function groupBySector(rows: ForecastRow[]): Map<string, ForecastRow[]> {
  const m = new Map<string, ForecastRow[]>()
  for (const r of rows) {
    const existing = m.get(r.zoom_sector_id)
    if (existing) existing.push(r)
    else m.set(r.zoom_sector_id, [r])
  }
  return m
}

// SVG line chart — actual (solid) + forecast (dashed) + shaded confidence band.
function SectorChart({
  label,
  rows,
  field,
  color,
  unit = '',
  yMin,
}: {
  label: string
  rows: ForecastRow[]
  field: keyof Pick<ForecastRow, 'predicted_eric_prb_util_rate' | 'predicted_eric_dl_user_ip_thpt' | 'predicted_eric_data_volume_ul_dl'>
  color: string
  unit?: string
  yMin?: number
}) {
  const W = 420
  const H = 160
  const pad = { top: 16, right: 12, bottom: 32, left: 40 }
  const iW = W - pad.left - pad.right
  const iH = H - pad.top - pad.bottom

  const vals = rows.map((r) => r[field] as number)
  const dataMax = Math.max(...vals, yMin ?? 0) * 1.15 || 1
  const dataMin = 0

  const x = (i: number) => pad.left + (i / Math.max(rows.length - 1, 1)) * iW
  const y = (v: number) => pad.top + iH - ((v - dataMin) / (dataMax - dataMin)) * iH

  const pts = rows.map((r, i) => `${x(i).toFixed(1)},${y(r[field] as number).toFixed(1)}`).join(' ')

  // Simple confidence band: ±15% of the value
  const upperPts = [
    `${x(0).toFixed(1)},${(pad.top + iH).toFixed(1)}`,
    ...rows.map((r, i) => `${x(i).toFixed(1)},${y((r[field] as number) * 1.15).toFixed(1)}`),
    `${x(rows.length - 1).toFixed(1)},${(pad.top + iH).toFixed(1)}`,
  ].join(' ')

  // X-axis labels — show first, last, and every ~4th
  const step = Math.max(1, Math.ceil(rows.length / 5))
  const xLabels = rows
    .filter((_, i) => i === 0 || i === rows.length - 1 || i % step === 0)
    .map((r) => {
      const i = rows.indexOf(r)
      const anchor = i === 0 ? 'start' : i === rows.length - 1 ? 'end' : 'middle'
      return `<text x="${x(i).toFixed(1)}" y="${H - 6}" text-anchor="${anchor}" font-size="8" fill="rgba(255,255,255,0.3)">W${r.week}</text>`
    })
    .join('')

  // Y-axis ticks
  const yTicks = [dataMax, dataMax * 0.5].map((v) => {
    const yy = y(v).toFixed(1)
    return `<line x1="${pad.left}" y1="${yy}" x2="${W - pad.right}" y2="${yy}" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
            <text x="${pad.left - 4}" y="${(parseFloat(yy) + 3).toFixed(1)}" text-anchor="end" font-size="8" fill="rgba(255,255,255,0.3)">${v.toFixed(0)}${unit}</text>`
  }).join('')

  // Congested dots
  const dots = rows.map((r, i) => {
    const fill = r.congested ? '#f87171' : color
    return `<circle cx="${x(i).toFixed(1)}" cy="${y(r[field] as number).toFixed(1)}" r="2.5" fill="${fill}"/>`
  }).join('')

  return (
    <div>
      <p style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'rgba(255,255,255,0.4)', marginBottom: 4 }}>
        {label}
      </p>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} xmlns="http://www.w3.org/2000/svg"
           style={{ display: 'block', maxWidth: '100%' }}>
        {yTicks}
        <polygon points={upperPts} fill={color} fillOpacity={0.08} />
        <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeDasharray="5,3" />
        <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeDasharray="none" />
        {dots}
        {xLabels}
      </svg>
    </div>
  )
}

export function ForecastModal({ siteId, rows, onClose }: Props) {
  const sectors = groupBySector(rows)
  const sectorIds = [...sectors.keys()].sort()

  return (
    <div
      className="fixed inset-0 z-[9999] flex flex-col"
      style={{ background: 'rgba(7,6,31,0.92)', backdropFilter: 'blur(8px)' }}
    >
      {/* Header */}
      <div style={{ background: 'linear-gradient(90deg,#1e3a5f,#1e1b4b)', padding: '14px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
        <div>
          <p style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'rgba(255,255,255,0.45)', marginBottom: 2 }}>
            Site Plot — KPIs (Forecast)
          </p>
          <p style={{ fontSize: 20, fontWeight: 800, color: '#fff' }}>{siteId}</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.45)' }}>
            {rows.length} forecast weeks · {sectorIds.length} sector{sectorIds.length !== 1 ? 's' : ''}
          </p>
          <button
            onClick={onClose}
            style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', color: '#fff', borderRadius: 8, padding: '6px 14px', cursor: 'pointer', fontWeight: 700, fontSize: 13 }}
          >
            ✕ Close
          </button>
        </div>
      </div>

      {/* Legend */}
      <div style={{ padding: '8px 24px', background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid rgba(255,255,255,0.06)', display: 'flex', gap: 20, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>
          <svg width="24" height="10"><line x1="0" y1="5" x2="24" y2="5" stroke="#fff" strokeWidth="1.5" strokeDasharray="5,3"/></svg>
          Forecast
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>
          <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: '#f87171' }}/>
          Congested week
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>
          <span style={{ display: 'inline-block', width: 24, height: 8, borderRadius: 2, background: 'rgba(255,255,255,0.06)' }}/>
          Confidence band (±15%)
        </div>
      </div>

      {/* Body — scrollable grid, one row per sector, 3 columns */}
      <div style={{ overflow: 'auto', flex: 1, padding: '16px 24px' }}>
        {/* Column headers */}
        <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr 1fr 1fr', gap: 12, marginBottom: 8 }}>
          <div/>
          <p style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'rgba(255,255,255,0.3)', textAlign: 'center' }}>Users (RRC)</p>
          <p style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'rgba(255,255,255,0.3)', textAlign: 'center' }}>PRB Util (%)</p>
          <p style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'rgba(255,255,255,0.3)', textAlign: 'center' }}>Throughput (Mbps)</p>
        </div>

        {sectorIds.map((secId) => {
          const secRows = sectors.get(secId)!
          const shortSec = secId.split('_').slice(-2).join('_')
          return (
            <div key={secId} style={{ display: 'grid', gridTemplateColumns: '120px 1fr 1fr 1fr', gap: 12, marginBottom: 12, alignItems: 'start', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: 12 }}>
              <div style={{ paddingTop: 20 }}>
                <p style={{ fontSize: 12, fontWeight: 700, color: '#6e9fff' }}>{shortSec}</p>
                <p style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', marginTop: 2 }}>{secRows.length} wks</p>
              </div>
              <SectorChart
                label=""
                rows={secRows}
                field="predicted_eric_data_volume_ul_dl"
                color="#60a5fa"
              />
              <SectorChart
                label=""
                rows={secRows}
                field="predicted_eric_prb_util_rate"
                color="#fb923c"
                unit="%"
                yMin={100}
              />
              <SectorChart
                label=""
                rows={secRows}
                field="predicted_eric_dl_user_ip_thpt"
                color="#4ade80"
              />
            </div>
          )
        })}

        {sectorIds.length === 0 && (
          <p style={{ textAlign: 'center', color: 'rgba(255,255,255,0.4)', marginTop: 60 }}>No forecast data available for this site.</p>
        )}
      </div>
    </div>
  )
}
