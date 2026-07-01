import type { HTMLAttributes } from 'react'

export function GlassPanel({ className = '', children, ...props }: HTMLAttributes<HTMLDivElement>) {
  // Decorative overlays live in their own overflow-hidden wrapper so they
  // clip to the rounded corners without clipping children — dropdown menus
  // (e.g. Map's draw-tool picker) need to visually escape the panel bounds.
  return (
    <div
      className={`relative rounded-3xl border border-white/12 bg-white/5 p-5 backdrop-blur-xl shadow-[0_12px_40px_-8px_rgba(0,0,0,0.6),inset_0_0_0_1px_rgba(255,255,255,0.08)] ${className}`}
      {...props}
    >
      {/* Grain texture — SVG turbulence rendered into a pseudo-layer */}
      <div
        className="pointer-events-none absolute inset-0 rounded-3xl opacity-[0.045]"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='200' height='200' filter='url(%23noise)'/%3E%3C/svg%3E")`,
          backgroundRepeat: 'repeat',
          backgroundSize: '180px 180px',
        }}
      />
      {/* Uniform thin edge highlight — all four sides, equal opacity */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden rounded-3xl">
        <div className="absolute inset-0 rounded-3xl ring-1 ring-inset ring-white/10" />
      </div>
      {children}
    </div>
  )
}
