// Replaces the old canvas particle stream (which wasn't reliably
// rendering) with a pure-CSS/SVG animated background: slow-drifting
// blue/yellow gradient blobs (CelcomDigi palette) under a grain texture,
// so there's no per-frame JS loop to silently fail.
export function AnimatedBackground() {
  return (
    <div className="fixed inset-0 overflow-hidden bg-ink-950">
      <div className="absolute inset-0">
        <div className="blob blob-blue-1" />
        <div className="blob blob-yellow-1" />
        <div className="blob blob-blue-2" />
        <div className="blob blob-yellow-2" />
      </div>
      <svg className="absolute inset-0 h-full w-full opacity-[0.05] mix-blend-overlay">
        <filter id="grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch" result="noise" />
          <feColorMatrix in="noise" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.9 0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#grain)" className="grain-shift" />
      </svg>
      <div className="absolute inset-0 bg-gradient-to-br from-ink-950/40 via-transparent to-ink-950/60" />
      <style>{`
        .blob {
          position: absolute;
          border-radius: 50%;
          filter: blur(70px);
          opacity: 0.55;
          will-change: transform;
        }
        .blob-blue-1 {
          top: -10%;
          left: -5%;
          width: 55vw;
          height: 55vw;
          background: radial-gradient(circle, #2a3fd6, transparent 70%);
          animation: drift1 26s ease-in-out infinite;
        }
        .blob-yellow-1 {
          top: 30%;
          right: -10%;
          width: 40vw;
          height: 40vw;
          background: radial-gradient(circle, #facc15, transparent 70%);
          opacity: 0.35;
          animation: drift2 32s ease-in-out infinite;
        }
        .blob-blue-2 {
          bottom: -15%;
          left: 20%;
          width: 50vw;
          height: 50vw;
          background: radial-gradient(circle, #3b82f6, transparent 70%);
          animation: drift3 38s ease-in-out infinite;
        }
        .blob-yellow-2 {
          bottom: 10%;
          right: 20%;
          width: 25vw;
          height: 25vw;
          background: radial-gradient(circle, #fbbf24, transparent 70%);
          opacity: 0.25;
          animation: drift1 22s ease-in-out infinite reverse;
        }
        @keyframes drift1 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(5%, 8%) scale(1.1); }
        }
        @keyframes drift2 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(-8%, 6%) scale(0.95); }
        }
        @keyframes drift3 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(6%, -6%) scale(1.05); }
        }
        .grain-shift {
          animation: grainShift 1.2s steps(4) infinite;
        }
        @keyframes grainShift {
          0% { transform: translate(0, 0); }
          25% { transform: translate(-1%, 1%); }
          50% { transform: translate(1%, -1%); }
          75% { transform: translate(-1%, -1%); }
          100% { transform: translate(0, 0); }
        }
      `}</style>
    </div>
  )
}
