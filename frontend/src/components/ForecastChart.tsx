import type { ForecastPredictionPoint, ForecastPoint } from '../lib/api'

const WIDTH = 720
const HEIGHT = 260
const PAD = { top: 16, right: 16, bottom: 28, left: 44 }

export function ForecastChart({
  actual,
  forecast,
  metricLabel,
}: {
  actual: ForecastPoint[]
  forecast: ForecastPredictionPoint[]
  metricLabel: string
}) {
  if (actual.length === 0) {
    return <p className="py-10 text-center text-sm text-white/50">No historical data for this site yet.</p>
  }

  const allDates = [...actual.map((p) => p.date), ...forecast.map((p) => p.date)]
  const allValues = [
    ...actual.map((p) => p.value),
    ...forecast.flatMap((p) => [p.value, p.ci_lower, p.ci_upper]),
  ]
  const yMin = Math.min(0, ...allValues)
  const yMax = Math.max(...allValues) * 1.1 || 1

  const plotW = WIDTH - PAD.left - PAD.right
  const plotH = HEIGHT - PAD.top - PAD.bottom

  const xScale = (i: number) => PAD.left + (allDates.length <= 1 ? 0 : (i / (allDates.length - 1)) * plotW)
  const yScale = (v: number) => PAD.top + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH

  const actualPoints = actual.map((p, i) => [xScale(i), yScale(p.value)] as const)
  const forecastStartIndex = actual.length - 1
  const forecastPoints = forecast.map((p, i) => [xScale(forecastStartIndex + 1 + i), yScale(p.value)] as const)

  const bandPath =
    forecast.length > 0
      ? [
          `M ${xScale(forecastStartIndex)} ${yScale(actual[actual.length - 1].value)}`,
          ...forecast.map((p, i) => `L ${xScale(forecastStartIndex + 1 + i)} ${yScale(p.ci_upper)}`),
          ...forecast
            .slice()
            .reverse()
            .map((p, i) => `L ${xScale(allDates.length - 1 - i)} ${yScale(p.ci_lower)}`),
          'Z',
        ].join(' ')
      : ''

  const actualPath = actualPoints.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ')
  const forecastPath =
    forecastPoints.length > 0
      ? `M ${xScale(forecastStartIndex)} ${yScale(actual[actual.length - 1].value)} ` +
        forecastPoints.map(([x, y]) => `L ${x} ${y}`).join(' ')
      : ''

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((t) => yMin + (yMax - yMin) * t)
  const labelEvery = Math.max(1, Math.floor(allDates.length / 6))

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full" style={{ maxHeight: HEIGHT }}>
      {yTicks.map((t) => (
        <g key={t}>
          <line x1={PAD.left} x2={WIDTH - PAD.right} y1={yScale(t)} y2={yScale(t)} stroke="rgba(255,255,255,0.08)" />
          <text x={PAD.left - 8} y={yScale(t)} textAnchor="end" dominantBaseline="middle" fontSize="10" fill="rgba(255,255,255,0.45)">
            {t.toFixed(0)}
          </text>
        </g>
      ))}

      {allDates.map((d, i) =>
        i % labelEvery === 0 ? (
          <text key={d} x={xScale(i)} y={HEIGHT - 8} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.4)">
            {d.slice(5)}
          </text>
        ) : null,
      )}

      {bandPath && <path d={bandPath} fill="rgba(56,189,248,0.15)" stroke="none" />}
      <path d={actualPath} fill="none" stroke="rgba(255,255,255,0.85)" strokeWidth={2} />
      {forecastPath && <path d={forecastPath} fill="none" stroke="#38bdf8" strokeWidth={2} strokeDasharray="6 4" />}

      {actualPoints.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={2.5} fill="rgba(255,255,255,0.85)" />
      ))}

      <text x={PAD.left} y={12} fontSize="10" fill="rgba(255,255,255,0.5)">
        {metricLabel}
      </text>
    </svg>
  )
}
