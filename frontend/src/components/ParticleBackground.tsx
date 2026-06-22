import { useEffect, useRef } from 'react'

const COLORS = ['255,210,63', '247,169,59', '255,196,92', '77,124,255', '110,160,255', '180,200,255', '60,90,200']

interface Particle {
  x: number
  y: number
  r: number
  color: string
  vx: number
  vy: number
  alpha: number
}

export function ParticleBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let width = window.innerWidth
    let height = window.innerHeight
    canvas.width = width
    canvas.height = height

    // Dense grainy stream: many small particles distributed along a
    // flowing diagonal band (yellow -> blue), not scattered uniformly —
    // matches the brand reference image's particle-cloud shape.
    const particles: Particle[] = []
    const count = 2200

    function spawn(): Particle {
      const band = Math.random()
      const cx = width * (0.05 + band * 0.9)
      const cy = height * (0.4 + Math.sin(band * 9) * 0.18)
      const spread = 90 + Math.sin(band * 14) * 50
      const colorIndex = Math.min(COLORS.length - 1, Math.floor(band * COLORS.length))
      return {
        x: cx + (Math.random() - 0.5) * spread * 2.6,
        y: cy + (Math.random() - 0.5) * spread,
        r: Math.random() * 2.6 + 0.8,
        color: COLORS[colorIndex],
        vx: (Math.random() - 0.5) * 0.12,
        vy: (Math.random() - 0.5) * 0.12,
        alpha: Math.random() * 0.5 + 0.5,
      }
    }

    for (let i = 0; i < count; i++) particles.push(spawn())

    let frameId: number
    function frame() {
      // Full clear (not a fading trail) keeps every particle at full
      // brightness every frame — a fade-trail was muddying density into
      // a faint haze instead of a crisp, dense grain field.
      ctx!.clearRect(0, 0, width, height)

      for (const p of particles) {
        p.x += p.vx
        p.y += p.vy
        if (p.x < -20 || p.x > width + 20) p.vx *= -1
        if (p.y < -20 || p.y > height + 20) p.vy *= -1

        ctx!.beginPath()
        ctx!.arc(p.x, p.y, p.r, 0, Math.PI * 2)
        ctx!.fillStyle = `rgba(${p.color},${p.alpha})`
        ctx!.shadowColor = `rgba(${p.color},${Math.min(p.alpha + 0.2, 1)})`
        ctx!.shadowBlur = p.r * 4
        ctx!.fill()
      }
      ctx!.shadowBlur = 0
      frameId = requestAnimationFrame(frame)
    }
    frame()

    function handleResize() {
      width = window.innerWidth
      height = window.innerHeight
      canvas!.width = width
      canvas!.height = height
    }
    window.addEventListener('resize', handleResize)

    return () => {
      cancelAnimationFrame(frameId)
      window.removeEventListener('resize', handleResize)
    }
  }, [])

  return (
    <div className="fixed inset-0 -z-10 overflow-hidden bg-ink-900">
      <canvas ref={canvasRef} className="h-full w-full" />
      <div className="absolute inset-0 bg-gradient-to-br from-ink-900/25 via-transparent to-ink-950/45" />
    </div>
  )
}
