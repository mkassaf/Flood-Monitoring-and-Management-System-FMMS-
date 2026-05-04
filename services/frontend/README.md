# frontend

React + TypeScript SPA. Map-based real-time dashboard with role-conditional
landing views.

## Bounded context

Talks **only** to the dashboard-bff. Never to any other service. Never directly
to Redis, Postgres, Kafka, or auth-service. The BFF is the contract.

## Stack

See `STACK.md` for versions.

- React 18 + TypeScript 5.4
- Vite 5
- TanStack Query for server state (REST polling + cache)
- Zustand for local UI state
- react-leaflet for the map (OSM tiles by default)
- Tailwind CSS for styling
- WebSocket client (native browser API)

## Layout

```
src/
├── api/                  # generated types + thin fetcher; types from BFF /openapi.json
├── auth/                 # login form, token storage (memory + sessionStorage), refresh
├── ws/                   # WebSocket client + reconnect/replay protocol
├── layouts/
│   ├── AreaManagerLayout.tsx
│   ├── CityManagerLayout.tsx
│   └── RegionalManagerLayout.tsx
├── pages/
│   ├── Login.tsx
│   ├── Dashboard.tsx     # routes to the right Layout based on user role
│   ├── AreaDetail.tsx
│   └── AlertHistory.tsx
├── components/
│   ├── Map.tsx
│   ├── SensorMarker.tsx
│   ├── AlertList.tsx
│   ├── AlertSeverityBadge.tsx
│   └── ParameterChart.tsx
├── store/                # zustand stores (alerts, sensors, ui)
└── App.tsx
```

## Role-conditional landing (FR-12, NFR-05)

On login, the user's role determines the initial layout:

- **Area Manager** — single map zoomed to their zone; live sensor markers;
  active alerts panel; per-sensor parameter charts on click.
- **City Manager** — overview of all zones in the city as colored polygons;
  alert summary per zone; click-through to a zone view.
- **Regional Manager** — region-level rollup; storm-style heatmap across cities;
  click-through.

QAS-06 measure: time-from-login to highest-severity-alert visible ≤3 s. Test
with Playwright in Phase 5.

## Real-time updates

1. On login, REST fetch initial state (`/me`, `/areas`, `/alerts/active`).
2. Open WebSocket at `wss://<bff>/ws` with token in `Authorization` header.
3. Maintain `last_seen_alert_id` in Zustand state.
4. On reconnect, send `{ "type": "resume", "last_seen_alert_id": ... }`.
5. Apply incoming deltas to Zustand stores. TanStack Query is invalidated
   selectively for affected entities.

## Configuration

Vite reads `VITE_*` env vars at build time:

| Var | Default | Notes |
|---|---|---|
| `VITE_BFF_URL` | `http://localhost:8080` | |
| `VITE_WS_URL` | derived from `VITE_BFF_URL` | |

## Run locally

```bash
cd services/frontend
npm install
npm run dev      # Vite dev server on :3000, HMR enabled
```

In Compose: `docker compose up frontend` builds and runs the production bundle
served by Vite preview. For active development prefer `npm run dev`.

## Tests

- Component tests with Vitest + React Testing Library.
- E2E with Playwright (Phase 5) — drives the demo cases via UI assertions.

## Critical paths

- **Token in memory only** when possible. SessionStorage is acceptable; never
  localStorage (XSS exposure).
- **Never bypass the BFF.** No direct fetches to other services.
- **Backpressure on the WS handler.** During a storm the BFF may push many
  messages per second; the client must coalesce updates per render frame to
  avoid React reconciliation thrashing.
