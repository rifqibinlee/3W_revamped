import { useRef, useState, useEffect } from 'react'
import { api, type IndoorSimResult } from '../lib/api'

// ── Types ────────────────────────────────────────────────────────────────────

interface WallDef {
  x0: number; y0: number   // pixels in display coords
  x1: number; y1: number
  material: string
  height_m: number
}

interface TxDef {
  x: number; y: number     // pixels in display coords
  power_dbm: number
  height_m: number
  label: string
}

const MATERIALS = ['concrete','brick','plasterboard','wood','glass','metal']
const FREQS = [
  { label: '2.4 GHz (WiFi)', value: 2400 },
  { label: '5 GHz (WiFi)',   value: 5000 },
  { label: '700 MHz (LTE)',  value: 700  },
  { label: '1800 MHz (LTE)', value: 1800 },
  { label: '2600 MHz (LTE)', value: 2600 },
  { label: '3500 MHz (5G)',  value: 3500 },
]
const RESOLUTIONS = [
  { label: '0.25 m (fine)', value: 0.25 },
  { label: '0.5 m',         value: 0.5  },
  { label: '1 m (fast)',    value: 1.0  },
]

const SNAP_RADIUS = 12  // pixels — snap to wall endpoint if within this distance

// ── Helpers ──────────────────────────────────────────────────────────────────

function svgCoords(e: React.MouseEvent<SVGSVGElement>): { x: number; y: number } {
  const rect = e.currentTarget.getBoundingClientRect()
  return { x: e.clientX - rect.left, y: e.clientY - rect.top }
}

// Closest point on segment (x0,y0)→(x1,y1) to point pt
function closestPointOnSegment(
  pt: { x: number; y: number },
  x0: number, y0: number, x1: number, y1: number,
): { x: number; y: number } {
  const dx = x1 - x0, dy = y1 - y0
  const lenSq = dx * dx + dy * dy
  if (lenSq === 0) return { x: x0, y: y0 }
  const t = Math.max(0, Math.min(1, ((pt.x - x0) * dx + (pt.y - y0) * dy) / lenSq))
  return { x: x0 + t * dx, y: y0 + t * dy }
}

// Snap to nearest wall endpoint first (preferred), then nearest point on any wall segment
function snapToWall(
  pt: { x: number; y: number },
  walls: WallDef[],
): { x: number; y: number; snapped: boolean } {
  let best: { x: number; y: number } | null = null
  let bestDist = SNAP_RADIUS

  // Pass 1: endpoints (preferred — higher priority so they win ties)
  for (const w of walls) {
    for (const end of [{ x: w.x0, y: w.y0 }, { x: w.x1, y: w.y1 }]) {
      const d = Math.hypot(pt.x - end.x, pt.y - end.y)
      if (d < bestDist) { bestDist = d; best = end }
    }
  }

  // Pass 2: point on segment — only if no endpoint was closer
  if (!best) {
    for (const w of walls) {
      const cp = closestPointOnSegment(pt, w.x0, w.y0, w.x1, w.y1)
      const d = Math.hypot(pt.x - cp.x, pt.y - cp.y)
      if (d < bestDist) { bestDist = d; best = cp }
    }
  }

  return best ? { ...best, snapped: true } : { ...pt, snapped: false }
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function IndoorSimulator({ onClose }: { onClose: () => void }) {
  // ── Floor plan image ────────────────────────────────────────────────────
  const [imgSrc, setImgSrc]           = useState<string | null>(null)
  const [imgAspect, setImgAspect]     = useState(4 / 3)    // w/h ratio of the image
  const [realWidthM, setRealWidthM]   = useState(30)       // user declares: image represents X metres wide
  const fileInputRef                  = useRef<HTMLInputElement>(null)
  const planInputRef                  = useRef<HTMLInputElement>(null)

  // ── Canvas size (SVG display area) ──────────────────────────────────────
  const containerRef                  = useRef<HTMLDivElement>(null)
  const [canvasW, setCanvasW]         = useState(800)
  const [canvasH, setCanvasH]         = useState(600)

  useEffect(() => {
    if (!containerRef.current) return
    const obs = new ResizeObserver(([entry]) => {
      const { width } = entry.contentRect
      setCanvasW(Math.floor(width))
      setCanvasH(Math.floor(width / imgAspect))
    })
    obs.observe(containerRef.current)
    return () => obs.disconnect()
  }, [imgAspect])

  // metres per pixel
  const scale     = realWidthM / canvasW
  const realHeightM = canvasH * scale

  // ── Drawing state ────────────────────────────────────────────────────────
  const [tool, setTool]               = useState<'select' | 'wall' | 'tx'>('select')
  const [walls, setWalls]             = useState<WallDef[]>([])
  const [txList, setTxList]           = useState<TxDef[]>([])
  const [drawStart, setDrawStart]     = useState<{ x: number; y: number } | null>(null)
  const [mouse, setMouse]             = useState<{ x: number; y: number }>({ x: 0, y: 0 })
  const [snapTarget, setSnapTarget]   = useState<{ x: number; y: number } | null>(null)
  const [selected, setSelected]       = useState<{ type: 'wall' | 'tx'; idx: number } | null>(null)

  // ── Parameters ───────────────────────────────────────────────────────────
  const [wallMat, setWallMat]         = useState('concrete')
  const [wallH, setWallH]             = useState(3.0)
  const [txPower, setTxPower]         = useState(20)
  const [txHeight, setTxHeight]       = useState(2.5)
  const [freq, setFreq]               = useState(2400)
  const [resolution, setResolution]   = useState(0.5)

  // ── Simulation ───────────────────────────────────────────────────────────
  const [loading, setLoading]         = useState(false)
  const [result, setResult]           = useState<IndoorSimResult | null>(null)
  const [viewMode, setViewMode]       = useState<'rsrp' | 'sinr'>('rsrp')
  const [error, setError]             = useState<string | null>(null)

  // ── Derived heatmap src + scale bounds ──────────────────────────────────
  const heatmapSrc = result
    ? (viewMode === 'sinr' && result.sinr_image_b64
        ? `data:image/png;base64,${result.sinr_image_b64}`
        : result.image_b64 ? `data:image/png;base64,${result.image_b64}` : null)
    : null

  const legendMin = result
    ? (viewMode === 'sinr' ? result.sinr_min : result.rsrp_min)
    : null
  const legendMax = result
    ? (viewMode === 'sinr' ? result.sinr_max : result.rsrp_max)
    : null
  const legendUnit = viewMode === 'sinr' ? 'dB' : 'dBm'

  // ── File upload ──────────────────────────────────────────────────────────
  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      setImgAspect(img.naturalWidth / img.naturalHeight)
      setImgSrc(url)
      setWalls([])
      setTxList([])
      setResult(null)
      setDrawStart(null)
    }
    img.src = url
  }

  // ── Save / Load plan ────────────────────────────────────────────────────
  function savePlan() {
    // Convert imgSrc (blob URL) to base64 so it survives as a file
    const doSave = (imageB64: string | null) => {
      const plan = {
        version: 1,
        realWidthM,
        imgAspect,
        imageB64,
        walls,
        txList,
        wallMat, wallH, txPower, txHeight, freq, resolution,
      }
      const blob = new Blob([JSON.stringify(plan, null, 2)], { type: 'application/json' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = 'floor-plan.3wplan'
      a.click()
      URL.revokeObjectURL(a.href)
    }

    if (!imgSrc) { doSave(null); return }

    // Fetch the blob URL and convert to base64
    fetch(imgSrc)
      .then(r => r.blob())
      .then(blob => new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(reader.result as string)
        reader.onerror = reject
        reader.readAsDataURL(blob)
      }))
      .then(b64 => doSave(b64))
      .catch(() => doSave(null))
  }

  function loadPlan(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''   // allow re-loading same file
    const reader = new FileReader()
    reader.onload = () => {
      try {
        const plan = JSON.parse(reader.result as string)
        if (plan.version !== 1) throw new Error('Unknown plan version')
        setRealWidthM(plan.realWidthM ?? 30)
        setImgAspect(plan.imgAspect ?? 4 / 3)
        setWalls(plan.walls ?? [])
        setTxList(plan.txList ?? [])
        setWallMat(plan.wallMat ?? 'concrete')
        setWallH(plan.wallH ?? 3.0)
        setTxPower(plan.txPower ?? 20)
        setTxHeight(plan.txHeight ?? 2.5)
        setFreq(plan.freq ?? 2400)
        setResolution(plan.resolution ?? 0.5)
        setResult(null)
        setDrawStart(null)
        setSelected(null)
        if (plan.imageB64) {
          const img = new Image()
          img.onload = () => setImgSrc(plan.imageB64)
          img.src = plan.imageB64
        } else {
          setImgSrc(null)
        }
      } catch {
        alert('Could not load plan file — invalid format.')
      }
    }
    reader.readAsText(file)
  }

  // ── SVG interaction ──────────────────────────────────────────────────────
  function handleSvgMouseMove(e: React.MouseEvent<SVGSVGElement>) {
    const raw = svgCoords(e)
    setMouse(raw)
    if (tool === 'wall') {
      const { x, y, snapped } = snapToWall(raw, walls)
      setSnapTarget(snapped ? { x, y } : null)
    } else {
      setSnapTarget(null)
    }
  }

  function handleSvgClick(e: React.MouseEvent<SVGSVGElement>) {
    // Allow clicks on background, image, lines, and decorative elements — block only
    // clicks that originated on interactive markers (walls/TXs handle their own stopPropagation)
    const tag = (e.target as Element).tagName
    if (tag === 'circle' || (tag === 'text' && (e.target as Element).getAttribute('data-interactive'))) return
    const raw = svgCoords(e)
    const { x, y } = snapToWall(raw, walls)
    const pt = { x, y }

    if (tool === 'wall') {
      if (!drawStart) {
        setDrawStart(pt)
      } else {
        setWalls(prev => [...prev, { x0: drawStart.x, y0: drawStart.y, x1: pt.x, y1: pt.y, material: wallMat, height_m: wallH }])
        setDrawStart(null)
        setSelected(null)
      }
    } else if (tool === 'tx') {
      setTxList(prev => [...prev, { x: pt.x, y: pt.y, power_dbm: txPower, height_m: txHeight, label: `AP${prev.length + 1}` }])
      setSelected(null)
    }
  }

  function handleSvgRightClick(e: React.MouseEvent<SVGSVGElement>) {
    e.preventDefault()
    if (drawStart) setDrawStart(null)
  }

  function deleteSelected() {
    if (!selected) return
    if (selected.type === 'wall') setWalls(prev => prev.filter((_, i) => i !== selected.idx))
    else setTxList(prev => prev.filter((_, i) => i !== selected.idx))
    setSelected(null)
  }

  // ── Add perimeter walls ──────────────────────────────────────────────────
  function addPerimeter() {
    const w = canvasW, h = canvasH, ht = wallH, mat = wallMat
    setWalls(prev => [...prev,
      { x0: 0, y0: 0, x1: w, y1: 0, material: mat, height_m: ht },
      { x0: w, y0: 0, x1: w, y1: h, material: mat, height_m: ht },
      { x0: w, y0: h, x1: 0, y1: h, material: mat, height_m: ht },
      { x0: 0, y0: h, x1: 0, y1: 0, material: mat, height_m: ht },
    ])
  }

  // ── Run simulation ───────────────────────────────────────────────────────
  async function runSimulation() {
    if (txList.length === 0) { setError('Place at least one AP first.'); return }
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await api.simulateIndoor({
        walls: walls.map(w => ({
          x0: w.x0 * scale, y0: (canvasH - w.y0) * scale,  // flip Y: SVG Y↓, Sionna Y↑
          x1: w.x1 * scale, y1: (canvasH - w.y1) * scale,
          height_m: w.height_m,
          material: w.material,
        })),
        tx_list: txList.map(t => ({
          x: t.x * scale,
          y: (canvasH - t.y) * scale,                       // flip Y
          height_m: t.height_m,
          power_dbm: t.power_dbm,
          azimuth_deg: 0,
        })),
        floor_origin_lat: 0,
        floor_origin_lng: 0,
        floor_width_m: realWidthM,
        floor_height_m: realHeightM,
        frequency_mhz: freq,
        resolution_m: resolution,
        rx_height_m: 1.0,
      })
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Simulation failed')
    } finally {
      setLoading(false)
    }
  }

  // ── Keyboard shortcuts ───────────────────────────────────────────────────
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { setDrawStart(null); setTool('select') }
      if (e.key === 'Delete' || e.key === 'Backspace') deleteSelected()
      if (e.key === 'w') setTool('wall')
      if (e.key === 't') setTool('tx')
      if (e.key === 's') setTool('select')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, walls, txList])

  // ── Cursor style ─────────────────────────────────────────────────────────
  const cursor = tool === 'wall' ? 'crosshair' : tool === 'tx' ? 'cell' : 'default'

  return (
    <div className="fixed inset-0 z-50 flex bg-[#0f1117]" onContextMenu={e => e.preventDefault()}>

      {/* ── Left sidebar ─────────────────────────────────────────────────── */}
      <aside className="flex w-64 flex-shrink-0 flex-col gap-4 overflow-y-auto border-r border-white/10 p-4">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-white">Indoor Simulator</h2>
            <p className="text-[10px] text-violet-300">Sionna RT · GPU ray tracing</p>
          </div>
          <button onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded-lg text-white/40 hover:bg-white/10 hover:text-white">
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6 6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>

        {/* Floor plan upload + save/load */}
        <section className="space-y-2">
          <p className="text-[10px] font-medium uppercase tracking-wider text-white/40">Floor Plan</p>
          <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleFileChange} />
          <input ref={planInputRef} type="file" accept=".3wplan,application/json" className="hidden" onChange={loadPlan} />
          <button onClick={() => fileInputRef.current?.click()}
            className="w-full rounded-lg border border-dashed border-white/20 py-3 text-xs text-white/40 hover:border-violet-400/50 hover:text-violet-300 transition-colors">
            {imgSrc ? '↑ Replace image' : '↑ Upload floor plan image'}
          </button>
          <div className="flex gap-2">
            <button onClick={() => planInputRef.current?.click()}
              className="flex-1 rounded-lg bg-white/5 py-1.5 text-xs text-white/50 hover:bg-white/10 transition-colors">
              📂 Load plan
            </button>
            <button onClick={savePlan}
              disabled={walls.length === 0 && txList.length === 0}
              className="flex-1 rounded-lg bg-violet-600/30 py-1.5 text-xs text-violet-200 hover:bg-violet-600/50 disabled:opacity-30 transition-colors">
              💾 Save plan
            </button>
          </div>
          <div className="flex items-center gap-2">
            <label className="flex-1 text-[10px] text-white/40">Real width (m)</label>
            <input type="number" value={realWidthM} min={1} max={10000}
              onChange={e => setRealWidthM(Number(e.target.value))}
              className="w-20 rounded bg-white/5 px-2 py-1 text-right text-xs text-white outline-none focus:ring-1 focus:ring-violet-400" />
          </div>
          {imgSrc && (
            <p className="text-[10px] text-white/30">
              Canvas: {realWidthM}m × {realHeightM.toFixed(1)}m
            </p>
          )}
        </section>

        {/* Drawing tools */}
        <section className="space-y-2">
          <p className="text-[10px] font-medium uppercase tracking-wider text-white/40">Draw Tools</p>
          <div className="grid grid-cols-3 gap-1">
            {([
              { id: 'select', label: 'Select', key: 'S', icon: '↖' },
              { id: 'wall',   label: 'Wall',   key: 'W', icon: '▬' },
              { id: 'tx',     label: 'AP',     key: 'T', icon: '📡' },
            ] as const).map(t => (
              <button key={t.id} onClick={() => { setTool(t.id); setDrawStart(null) }}
                className={`flex flex-col items-center gap-0.5 rounded-lg py-2 text-[10px] transition-colors
                  ${tool === t.id ? 'bg-violet-500/30 text-violet-200' : 'bg-white/5 text-white/40 hover:bg-white/10 hover:text-white'}`}>
                <span className="text-base leading-none">{t.icon}</span>
                <span>{t.label}</span>
                <span className="text-[8px] text-white/25">[{t.key}]</span>
              </button>
            ))}
          </div>
          {selected && (
            <button onClick={deleteSelected} className="w-full rounded-lg bg-red-500/10 py-1 text-xs text-red-400 hover:bg-red-500/20">
              Delete selected [Del]
            </button>
          )}
          {tool === 'wall' && (
            <p className="text-[10px] text-white/30">
              {drawStart ? 'Click to finish wall • Right-click to cancel' : 'Click to start a wall'}
            </p>
          )}
          {tool === 'tx' && (
            <p className="text-[10px] text-white/30">Click to place an access point</p>
          )}
        </section>

        {/* Wall parameters */}
        <section className="space-y-2">
          <p className="text-[10px] font-medium uppercase tracking-wider text-white/40">Wall Settings</p>
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-white/40">Material</span>
            <select value={wallMat} onChange={e => setWallMat(e.target.value)}
              className="w-full rounded bg-white/5 px-2 py-1 text-xs text-white outline-none">
              {MATERIALS.map(m => <option key={m} value={m}>{m.charAt(0).toUpperCase() + m.slice(1)}</option>)}
            </select>
          </label>
          <label className="flex items-center justify-between gap-2">
            <span className="text-[10px] text-white/40">Height (m)</span>
            <input type="number" value={wallH} min={0.5} max={30} step={0.5}
              onChange={e => setWallH(Number(e.target.value))}
              className="w-16 rounded bg-white/5 px-2 py-1 text-right text-xs text-white outline-none focus:ring-1 focus:ring-violet-400" />
          </label>
          <button onClick={addPerimeter} className="w-full rounded-lg bg-white/5 py-1.5 text-xs text-white/50 hover:bg-white/10">
            + Add perimeter walls
          </button>
        </section>

        {/* AP parameters */}
        <section className="space-y-2">
          <p className="text-[10px] font-medium uppercase tracking-wider text-white/40">AP Settings</p>
          <label className="flex items-center justify-between gap-2">
            <span className="text-[10px] text-white/40">TX Power (dBm)</span>
            <input type="number" value={txPower} min={0} max={40}
              onChange={e => setTxPower(Number(e.target.value))}
              className="w-16 rounded bg-white/5 px-2 py-1 text-right text-xs text-white outline-none focus:ring-1 focus:ring-violet-400" />
          </label>
          <label className="flex items-center justify-between gap-2">
            <span className="text-[10px] text-white/40">AP Height (m)</span>
            <input type="number" value={txHeight} min={0.1} max={10} step={0.1}
              onChange={e => setTxHeight(Number(e.target.value))}
              className="w-16 rounded bg-white/5 px-2 py-1 text-right text-xs text-white outline-none focus:ring-1 focus:ring-violet-400" />
          </label>
        </section>

        {/* Simulation parameters */}
        <section className="space-y-2">
          <p className="text-[10px] font-medium uppercase tracking-wider text-white/40">Simulation</p>
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-white/40">Frequency</span>
            <select value={freq} onChange={e => setFreq(Number(e.target.value))}
              className="w-full rounded bg-white/5 px-2 py-1 text-xs text-white outline-none">
              {FREQS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-white/40">Resolution</span>
            <select value={resolution} onChange={e => setResolution(Number(e.target.value))}
              className="w-full rounded bg-white/5 px-2 py-1 text-xs text-white outline-none">
              {RESOLUTIONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </label>
        </section>

        {/* Summary */}
        <section className="space-y-1 text-[10px] text-white/30">
          <div className="flex justify-between"><span>Walls</span><span className="text-white/50">{walls.length}</span></div>
          <div className="flex justify-between"><span>APs</span><span className="text-white/50">{txList.length}</span></div>
          {result && <div className="flex justify-between"><span>Sim time</span><span className="text-white/50">{result.simulation_time_s}s</span></div>}
        </section>

        {/* Run button */}
        <div className="mt-auto space-y-2">
          {error && <p className="rounded-lg bg-red-500/10 px-3 py-2 text-[10px] text-red-400">{error}</p>}
          {result && (
            <div className="flex gap-1">
              {(['rsrp','sinr'] as const).map(m => (
                <button key={m} onClick={() => setViewMode(m)}
                  className={`flex-1 rounded py-1 text-[10px] uppercase ${viewMode === m ? 'bg-violet-500/30 text-violet-200' : 'bg-white/5 text-white/40 hover:bg-white/10'}`}>
                  {m}
                </button>
              ))}
            </div>
          )}
          <button onClick={runSimulation} disabled={loading || txList.length === 0}
            className="w-full rounded-lg bg-violet-600 py-2.5 text-xs font-semibold text-white disabled:opacity-40 hover:bg-violet-500 transition-colors">
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                  <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83" strokeLinecap="round"/>
                </svg>
                Simulating…
              </span>
            ) : '⚡ Run Sionna RT'}
          </button>
        </div>
      </aside>

      {/* ── Canvas area ──────────────────────────────────────────────────── */}
      <div className="relative flex flex-1 flex-col overflow-hidden">

        {/* Toolbar strip */}
        <div className="flex h-9 flex-shrink-0 items-center gap-3 border-b border-white/10 px-4 text-[10px] text-white/30">
          <span>W · Wall</span><span>T · AP</span><span>S · Select</span><span>Del · Remove</span><span>Esc · Cancel</span>
          {drawStart && <span className="ml-auto text-violet-300 animate-pulse">Drawing wall… right-click to cancel</span>}
          {!imgSrc && <span className="ml-auto">Upload a floor plan image to get started</span>}
        </div>

        {/* SVG canvas */}
        <div ref={containerRef} className="relative flex-1 overflow-hidden bg-[#161921]">
          {!imgSrc && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-white/20">
              <svg viewBox="0 0 24 24" className="h-12 w-12" fill="none" stroke="currentColor" strokeWidth="1">
                <rect x="3" y="3" width="18" height="18" rx="1"/>
                <path d="M3 9h18M9 21V9"/>
              </svg>
              <p className="text-sm">Upload a floor plan image from the left panel</p>
              <p className="text-xs">PNG, JPG, or SVG · Set the real-world width in metres</p>
            </div>
          )}

          {imgSrc && (
            <svg
              width={canvasW}
              height={canvasH}
              style={{ cursor, display: 'block', userSelect: 'none', WebkitUserSelect: 'none' }}
              onClick={handleSvgClick}
              onMouseMove={handleSvgMouseMove}
              onContextMenu={handleSvgRightClick}
            >
              {/* Floor plan image background */}
              <image href={imgSrc} x={0} y={0} width={canvasW} height={canvasH} preserveAspectRatio="none" />

              {/* Heatmap overlay */}
              {heatmapSrc && (
                <image href={heatmapSrc} x={0} y={0} width={canvasW} height={canvasH}
                  preserveAspectRatio="none" style={{ opacity: 0.6 }} />
              )}

              {/* Committed walls */}
              {walls.map((w, i) => {
                const mx = (w.x0 + w.x1) / 2
                const my = (w.y0 + w.y1) / 2
                const dx = w.x1 - w.x0
                const dy = w.y1 - w.y0
                const lenPx = Math.hypot(dx, dy)
                const lenM = (lenPx * scale).toFixed(1)
                // Angle in degrees for text rotation; keep text readable (flip if upside-down)
                let angleDeg = Math.atan2(dy, dx) * 180 / Math.PI
                if (angleDeg > 90 || angleDeg < -90) angleDeg += 180
                const isSelected = selected?.type === 'wall' && selected.idx === i
                return (
                  <g key={i} onClick={e => { e.stopPropagation(); setSelected({ type: 'wall', idx: i }) }}>
                    <line x1={w.x0} y1={w.y0} x2={w.x1} y2={w.y1}
                      stroke={isSelected ? '#a78bfa' : '#60a5fa'}
                      strokeWidth={isSelected ? 3 : 2}
                      strokeLinecap="round" />
                    {/* Length label — shown when wall is long enough to fit text */}
                    {lenPx > 30 && (
                      <text
                        x={mx} y={my}
                        textAnchor="middle" dominantBaseline="central"
                        fontSize={10} fill={isSelected ? '#c4b5fd' : '#93c5fd'}
                        fontWeight="600"
                        transform={`rotate(${angleDeg}, ${mx}, ${my}) translate(0, -7)`}
                        style={{ pointerEvents: 'none' }}
                      >
                        {lenM}m
                      </text>
                    )}
                    {/* Invisible wider hit area */}
                    <line x1={w.x0} y1={w.y0} x2={w.x1} y2={w.y1}
                      stroke="transparent" strokeWidth={12} style={{ cursor: 'pointer' }} />
                  </g>
                )
              })}

              {/* Preview wall while drawing */}
              {drawStart && (
                <line x1={drawStart.x} y1={drawStart.y}
                  x2={snapTarget ? snapTarget.x : mouse.x}
                  y2={snapTarget ? snapTarget.y : mouse.y}
                  stroke="#a78bfa" strokeWidth={2} strokeDasharray="6 3" strokeLinecap="round" opacity={0.8}
                  style={{ pointerEvents: 'none' }} />
              )}

              {/* Start point dot */}
              {drawStart && (
                <circle cx={drawStart.x} cy={drawStart.y} r={4} fill="#a78bfa"
                  style={{ pointerEvents: 'none' }} />
              )}

              {/* Snap indicator — green ring when cursor is near an existing endpoint */}
              {snapTarget && (
                <circle cx={snapTarget.x} cy={snapTarget.y} r={SNAP_RADIUS}
                  fill="none" stroke="#4ade80" strokeWidth={2} opacity={0.9}
                  style={{ pointerEvents: 'none' }} />
              )}

              {/* Access points */}
              {txList.map((t, i) => (
                <g key={i} style={{ cursor: 'pointer' }}
                  onClick={e => { e.stopPropagation(); setSelected({ type: 'tx', idx: i }) }}>
                  <circle cx={t.x} cy={t.y} r={10}
                    fill={selected?.type === 'tx' && selected.idx === i ? '#7c3aed' : '#4f46e5'}
                    stroke={selected?.type === 'tx' && selected.idx === i ? '#a78bfa' : '#818cf8'}
                    strokeWidth={2} />
                  <text x={t.x} y={t.y + 1} textAnchor="middle" dominantBaseline="middle"
                    fontSize={8} fill="white" fontWeight="bold" style={{ pointerEvents: 'none' }}>
                    AP
                  </text>
                  <text x={t.x} y={t.y + 16} textAnchor="middle" fontSize={9} fill="white" opacity={0.7}
                    style={{ pointerEvents: 'none' }}>
                    {t.label}
                  </text>
                </g>
              ))}

              {/* Scale ruler (bottom-left) — pointer-events:none so it never blocks canvas clicks */}
              <g transform={`translate(16, ${canvasH - 20})`} style={{ pointerEvents: 'none' }}>
                <line x1={0} y1={0} x2={1 / scale} y2={0} stroke="white" strokeWidth={2} opacity={0.5} />
                <line x1={0} y1={-4} x2={0} y2={4} stroke="white" strokeWidth={1.5} opacity={0.5} />
                <line x1={1 / scale} y1={-4} x2={1 / scale} y2={4} stroke="white" strokeWidth={1.5} opacity={0.5} />
                <text x={1 / scale / 2} y={-6} textAnchor="middle" fontSize={9} fill="white" opacity={0.5}>1 m</text>
              </g>

              {/* Crosshair coords (bottom-right) */}
              <text x={canvasW - 8} y={canvasH - 8} textAnchor="end" fontSize={9} fill="white" opacity={0.3}
                style={{ pointerEvents: 'none' }}>
                {(mouse.x * scale).toFixed(1)}m, {((canvasH - mouse.y) * scale).toFixed(1)}m
              </text>

              {/* Colorbar legend (top-right) — shows auto-scaled range */}
              {heatmapSrc && legendMin != null && legendMax != null && (() => {
                const barW = 12, barH = 100, x0 = canvasW - 52, y0 = 12
                const stops = viewMode === 'sinr'
                  ? [['#006837','0%'],['#78c679','33%'],['#ffff00','66%'],['#d73027','100%']]
                  : [['#0d0887','0%'],['#7e03a8','33%'],['#f89540','66%'],['#f0f921','100%']]
                return (
                  <g transform={`translate(${x0}, ${y0})`} style={{ pointerEvents: 'none' }}>
                    <defs>
                      <linearGradient id="cb-grad" x1="0" y1="1" x2="0" y2="0">
                        {stops.map(([color, offset]) => (
                          <stop key={offset} offset={offset} stopColor={color} />
                        ))}
                      </linearGradient>
                    </defs>
                    <rect x={0} y={0} width={barW} height={barH}
                      fill="url(#cb-grad)" rx={2} opacity={0.85} />
                    <rect x={0} y={0} width={barW} height={barH}
                      fill="none" stroke="white" strokeWidth={0.5} rx={2} opacity={0.4} />
                    <text x={barW + 4} y={4} fontSize={8} fill="white" opacity={0.8} dominantBaseline="hanging">
                      {legendMax?.toFixed(0)}{legendUnit}
                    </text>
                    <text x={barW + 4} y={barH} fontSize={8} fill="white" opacity={0.8} dominantBaseline="auto">
                      {legendMin?.toFixed(0)}{legendUnit}
                    </text>
                  </g>
                )
              })()}
            </svg>
          )}
        </div>
      </div>
    </div>
  )
}
