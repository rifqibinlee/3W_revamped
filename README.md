# 3W+ Platform

RAN congestion analytics, AI-assisted network planning, and GIS-based site planning for CelcomDigi. Consolidates PRB/throughput forecasting, road-routing for power-source siting, CCTV planning, kanban project tracking, and an AI chat agent into one web application.

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python 3.10+) + Uvicorn |
| Analytics DB | DuckDB over local Parquet files |
| Relational / RAG | PostgreSQL 16 + pgvector |
| Object storage | MinIO (local) / AWS S3 (production) |
| Frontend | React 19 + Vite + Tailwind v4 + MapLibre GL |
| AI agent | LangGraph + LangChain, Claude (primary) / Ollama (dev fallback) |
| Spatial | GeoServer (WMS/WFS), OSMnx, Shapely, NetworkX |
| Infra | Docker Compose (local), EC2 + nginx (production) |

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Docker Desktop | latest | Required for all deployment modes |
| Node.js | 20 LTS | Frontend build only |
| Python | 3.10+ | Backend local dev only |
| QGIS | 3.16+ | Optional — for the road-routing `.model3` |

---

## Quick Start (Docker — recommended)

This is the one-command path. Docker handles Python, Postgres, and nginx.

**1. Clone and configure**

```bash
git clone https://github.com/rifqibinlee/3W_revamped.git
cd 3W_revamped
```

Copy and fill in the backend configuration:

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and set at minimum:

```
POSTGRES_PASSWORD=<strong-password>
JWT_SECRET=<run: python -c "import secrets; print(secrets.token_hex(32))">
ANTHROPIC_API_KEY=<your-key>    # optional — Chat falls back to Ollama without this
```

**2. Build the frontend**

```bash
cd frontend
npm install
npm run build
cd ..
```

**3. Start all services**

```bash
docker compose -f infra/docker-compose.yml --env-file backend/.env up -d
```

This starts: `postgres`, `backend` (FastAPI), `nginx` (serves frontend + proxies API), and `geoserver`.

**4. Run database migrations**

Wait ~10 seconds for Postgres to initialise, then:

```bash
docker compose -f infra/docker-compose.yml exec backend alembic upgrade head
```

**5. Create the first Super Admin user**

```bash
docker compose -f infra/docker-compose.yml exec backend \
  python -c "
from app.auth.router import _create_user_internal
_create_user_internal('admin', 'admin@example.com', 'changeme', 'super_admin')
"
```

**6. Open the app**

```
http://localhost:5000
```

Log in with the credentials you set above. Change the password immediately from the profile menu.

---

## Windows Desktop Launcher (`.exe`)

A one-click launcher is included for Windows users who prefer not to use the terminal.

### Build the exe (once)

Install PyInstaller globally or in any Python 3.10+ environment:

```powershell
pip install pyinstaller
```

Then from the repo root:

```powershell
python -m PyInstaller --onefile --noconsole --name "3W+" launcher.py
```

The output is `dist/3W+.exe` (~9 MB, self-contained).

### Using the launcher

1. Make sure Docker Desktop is running.
2. Ensure `backend/.env` exists (the launcher copies `.env.example` for you on first run and prompts you to fill it in).
3. Double-click `dist/3W+.exe`.

The launcher will:
- Verify Docker Desktop is reachable
- Start the Docker Compose stack (`docker compose up -d`)
- Poll `http://localhost:5000/health` until the backend is ready
- Open your default browser at `http://localhost:5000`

> The exe is a launcher only — the actual services run inside Docker containers. Docker Desktop must remain running while you use the app.

---

## Local Development (no Docker)

Use this mode when actively developing backend or frontend code.

### Infrastructure (Postgres only)

```bash
docker compose -f infra/docker-compose.yml --env-file backend/.env up -d postgres
```

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

pip install -e ".[dev]"
```

Copy and configure the env file if you haven't already:

```bash
cp .env.example .env
# Edit .env — set POSTGRES_DSN to point to localhost:5432
```

Run migrations and start the server:

```bash
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
npm run dev
```

App: http://localhost:5173 (proxies `/api` to the backend at `:8000` automatically via Vite).

### Tests

```bash
# Backend
cd backend && pytest -q

# Frontend
cd frontend && npm test
```

---

## Production Deploy (AWS EC2)

Run the deploy script on your EC2 instance (Amazon Linux 2023 / ARM):

```bash
# SSH into EC2
git clone https://github.com/rifqibinlee/3W_revamped.git
cd 3W_revamped
cp backend/.env.example backend/.env
# Edit backend/.env — set EC2_HOST, POSTGRES_PASSWORD, JWT_SECRET, ANTHROPIC_API_KEY, USE_REAL_S3, etc.
bash deploy.sh
```

The script builds the frontend, pulls/builds Docker images, starts all services, and verifies the health endpoint. All services restart automatically on reboot via Docker's `restart: always` policy.

The app is served at `http://<ec2-ip>:5000` (nginx). Put a reverse proxy with TLS in front of this for HTTPS.

---

## Service Ports

| Service | Port | Notes |
|---|---|---|
| App (nginx) | 5000 | Main entry point — serves frontend + proxies API |
| Backend (FastAPI) | 8000 | Direct API access in dev mode only |
| Frontend (Vite dev) | 5173 | Dev mode only |
| GeoServer | 8600 | Admin UI at `:8600/geoserver/web` |
| PostgreSQL | 5432 | Internal; exposed only within Docker network in production |

---

## Configuration Reference (`backend/.env`)

| Variable | Required | Description |
|---|---|---|
| `POSTGRES_PASSWORD` | Yes | Postgres password (used by both the DB container and DSN) |
| `POSTGRES_USER` | No | Default: `threew` |
| `POSTGRES_DB` | No | Default: `threew` |
| `POSTGRES_DSN` | Dev only | Full SQLAlchemy DSN; overridden by docker-compose in production |
| `JWT_SECRET` | Yes | 32+ character random hex string (`python -c "import secrets; print(secrets.token_hex(32))"`) |
| `ANTHROPIC_API_KEY` | No | Enables Claude in the Chat agent; falls back to Ollama if blank |
| `ANTHROPIC_MODEL` | No | Default: `claude-sonnet-4-6` |
| `USE_REAL_S3` | No | Set `true` on EC2 to read/write Parquet from S3 instead of local disk |
| `AWS_REGION` | No | Default: `ap-southeast-1` |
| `S3_BUCKET` | No | S3 bucket name when `USE_REAL_S3=true` |
| `DUCKDB_PATH` | No | Default: `./data/analytics.duckdb` |
| `PARQUET_DIR` | No | Default: `./data/parquet` |
| `EC2_HOST` | Prod | EC2 public IP or domain — added to CORS allowed origins |
| `GEOSERVER_URL` | No | Default: `http://localhost:8600/geoserver`; auto-set by compose |

---

## Data Pipeline

After first login, go to **Data Management** (Admin role required) to upload and process datasets:

1. Upload the `.xlsb` cell-reference file, raw xC/xD Parquet files, and site coordinate data.
2. Click **Run Full Pipeline** — this ingests all stages into DuckDB and writes processed Parquet.
3. Upload substations/electric pole GeoPackage files for offline road routing (optional but recommended).
4. Click **Sync Knowledge Base** to index documents for the AI Chat RAG search.

---

## QGIS Road Routing Model

`qgis_models/genset_road_routing.model3` replicates the platform's genset-routing logic in QGIS for offline use.

**Load in QGIS 3.16+:**

1. Processing → Toolbox → Open Existing Model → select `genset_road_routing.model3`
2. Provide: Cell Site (point), Power Sources (point), Road Network (line), Max Distance in metres (default 2000)
3. Run — output is a ranked line layer of road paths to each reachable power source

**CRS note:** Reproject all layers to **EPSG:32647** (UTM Zone 47N) for accurate metre-based distances over Peninsular Malaysia.

---

## Project Structure

```
3W_revamped/
├── backend/
│   ├── app/
│   │   ├── auth/          JWT authentication + user management
│   │   ├── analytics/     DuckDB query layer (congestion, forecasts, CAPEX)
│   │   ├── siteplanning/  Genset routing, CCTV, coverage simulation
│   │   ├── coverage/      Sionna RT indoor propagation
│   │   ├── agent/         LangGraph AI agent
│   │   ├── rag/           pgvector RAG (document ingestion + retrieval)
│   │   ├── ingestion/     ETL pipeline stages (cell_reference, congestion, forecasts, CAPEX)
│   │   ├── datamgmt/      Upload + pipeline trigger endpoints
│   │   ├── annotations/   Projects, tasks, notes
│   │   ├── chat/          Conversation history
│   │   ├── pricing/       CAPEX pricing JSON loader
│   │   ├── geoserver/     WMS/WFS layer proxy
│   │   └── reviews/       (coming soon)
│   ├── migrations/        Alembic migrations
│   └── pyproject.toml
├── frontend/
│   └── src/
│       ├── pages/         Map, Dashboard, Projects, Chat, CAPEX, Notes, Data, SuperAdmin
│       ├── components/    Reusable UI components
│       └── lib/api.ts     Typed API client
├── infra/
│   ├── docker-compose.yml
│   └── nginx.conf
├── docs/
│   └── user_manual.html   Full user manual (open in browser)
├── qgis_models/
│   └── genset_road_routing.model3
├── launcher.py            Windows GUI launcher source
└── deploy.sh              EC2 one-shot deploy script
```

---

## Stopping the Stack

```bash
# Stop and keep data
docker compose -f infra/docker-compose.yml down

# Stop and wipe all data (destructive)
docker compose -f infra/docker-compose.yml down -v
```

---

## User Manual

Open `docs/user_manual.html` in any browser for the full illustrated user manual covering all modules.
