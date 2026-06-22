import type { HTMLAttributes } from 'react'

export function GlassPanel({ className = '', children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-3xl border border-white/15 bg-white/8 p-5 backdrop-blur-xl ${className}`}
      {...props}
    >
      {children}
    </div>
  )
}
