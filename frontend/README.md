# 3W Revamped — Frontend

React 19 + Vite + TypeScript + Tailwind v4 + MapLibre GL. See the [repo root README](../README.md)
for the full-stack overview and [docs/REBUILD_PLAN.md](../docs/REBUILD_PLAN.md) for what's built.

## Setup

```bash
npm install
cp .env.example .env   # if present — sets VITE_API_BASE_URL; defaults to http://localhost:8000
npm run dev
```

The backend (see [../backend](../backend)) must be running for anything beyond the login page to
work — every page fetches real data, there's no mock-data mode.

## Scripts

| Command | Does |
|---|---|
| `npm run dev` | Vite dev server with HMR |
| `npm run build` | Typecheck (`tsc -b`) + production build |
| `npm run lint` | ESLint |
| `npm run test` | Vitest |
| `npm run preview` | Serve the production build locally |

## Structure

- `src/pages/` — one file per route (Dashboard, Map, Notes, Projects, Chat, Pricing, Agent, DataManagement)
- `src/components/` — shared UI (`GlassPanel`, `DataTable`, `Pagination`, `AnimatedBackground`, `ForecastChart`, …)
- `src/lib/api.ts` — typed fetch client; every backend endpoint used by the UI has a typed method here
- `src/lib/auth.tsx` / `authContext.ts` / `useAuth.ts` — split across three files (not one) because a file
  exporting both a component and a non-component hook trips `react-refresh/only-export-components`

## Conventions

- No mock data — pages call the real backend; if an endpoint doesn't exist yet, the page should say so
  rather than fabricate data.
- Tailwind v4 theme tokens (fonts, ink/accent/sky colors) live in `src/index.css` under `@theme`, not a
  JS config file.
- Background/decorative elements should avoid explicit `z-index` where possible — an earlier version of
  `AnimatedBackground` used `-z-10`, which creates its own stacking context and silently traps everything
  inside it below the rest of the page regardless of any z-index set on its children. Plain DOM order
  (background first, content second) is simpler and was the actual fix.
