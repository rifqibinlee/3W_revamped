import type { HTMLAttributes } from 'react'

export function GlassPanel({ className = '', children, ...props }: HTMLAttributes<HTMLDivElement>) {
  // Background/border stay simple solid utilities (bg-white/8, border-white/20)
  // so callers can still override them with e.g. `bg-green-400/5` for a status
  // panel — the glossier look comes entirely from the shadow (depth + inset
  // highlight) and the two overlay divs (top shine line, soft corner glow),
  // which layer on top regardless of the base color.
  // The decorative shine/glow live in their own overflow-hidden layer so
  // they stay clipped to the rounded corners without clipping the panel's
  // actual children — a dropdown menu (e.g. Map's draw-tool picker) needs
  // to visually escape the panel bounds, which `overflow-hidden` on the
  // panel itself would silently clip.
  return (
    <div
      className={`relative rounded-3xl border border-white/20 bg-white/8 p-5 backdrop-blur-xl shadow-[0_8px_32px_-8px_rgba(0,0,0,0.45),inset_0_1px_0_0_rgba(255,255,255,0.2),inset_0_-1px_12px_0_rgba(0,0,0,0.15)] ${className}`}
      {...props}
    >
      <div className="pointer-events-none absolute inset-0 overflow-hidden rounded-3xl">
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/50 to-transparent" />
        <div className="absolute -left-1/3 -top-1/3 h-2/3 w-2/3 rounded-full bg-white/8 blur-3xl" />
      </div>
      {children}
    </div>
  )
}
