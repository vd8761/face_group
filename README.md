# PhotoGroup — AI Face Grouping for Event Photos

AI-powered photo management for events. Organizers upload photos; attendees scan their face and instantly find every picture they appear in — downloadable as individual files or a bulk ZIP.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19 + Vite (deployed on **Vercel**) |
| Backend API | FastAPI (Python 3.11, deployed on **Render**) |
| ML Pipeline | InsightFace `buffalo_l` (RetinaFace + ArcFace, CUDA or CPU ONNX) |
| Clustering | Event-scoped, constrained cosine grouping with same-photo safeguards |
| Database | **Neon DB** (serverless PostgreSQL) |
| Object Storage | **Cloudflare R2** ($0 egress) |
| Job Queue | **Upstash Redis** + Celery |
| Background Worker | Celery worker on **Render** |

---

## Prerequisites

- Python 3.11+ (for Render; Python 3.9+ minimum)
- Node.js 18+
- Accounts: [Neon DB](https://neon.tech), [Cloudflare R2](https://cloudflare.com), [Upstash](https://upstash.com), [Render](https://render.com), [Vercel](https://vercel.com)

---

## Local Development Setup

### 1. Clone & configure backend

```bash
cd backend
cp .env.example .env
# Fill in all values in .env (see below)
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Start the backend

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be at `http://localhost:8000`.
- Swagger docs: `http://localhost:8000/api/docs`
- Health check: `http://localhost:8000/api/health`

### 4. Start the Celery worker (separate terminal)

Linux / Ubuntu:

```bash
cd backend
./worker-start.sh
```

Windows PowerShell (activate `backend/.venv` first):

```powershell
cd backend
.\worker-start.ps1
```

The managed launcher starts two Celery nodes. Face inference consumes
`face-v2,celery`; Google Drive downloads consume `drive-downloads`, so network
waits cannot occupy the GPU-facing worker. Ubuntu/Linux uses a conservative
resource-aware prefork pool that begins at one child and grows one at a time.
Windows uses two `solo` nodes at concurrency one because Celery cannot safely
resize that pool. Each prefork child owns a separate InsightFace model; tune the
`WORKER_AUTOSCALE_*` memory budgets only after GPU soak testing.

### 5. Frontend

```bash
cd frontend
npm install
npm run dev
```

App at `http://localhost:5173`

---

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and fill in:

| Variable | Where to get it |
|----------|----------------|
| `SECRET_KEY` | Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SUPER_ADMIN_PASSWORD` | Choose a strong password |
| `DATABASE_URL` | Neon DB → your project → Connection string (use `postgresql+asyncpg://...`) |
| `R2_ACCOUNT_ID` | Cloudflare Dashboard → R2 |
| `R2_ACCESS_KEY_ID` | Cloudflare → R2 → Manage API Tokens |
| `R2_SECRET_ACCESS_KEY` | Same as above |
| `R2_BUCKET_NAME` | Create a bucket named `photogroup-photos` |
| `REDIS_URL` | Upstash → Create Redis → `.env` tab (use `rediss://...`) |
| `GOOGLE_DRIVE_API_KEY` | Optional Google Cloud API key for public Drive-folder imports |

The face model is deliberately pinned to `buffalo_l`. If the model or pipeline
version changes, reprocess existing originals before comparing embeddings; two
different model packs can both produce 512-value vectors that are not mutually
compatible.

---

## Cloud Deployment

### Backend → Render

1. Push the repo to GitHub
2. Go to [render.com](https://render.com) → New → Blueprint
3. Point to `render.yaml` in the repo root
4. Fill in all `sync: false` env vars in the Render dashboard
5. Deploy — Render creates both the web service and worker

### Frontend → Vercel

```bash
cd frontend
npx vercel --prod
```

Set `VITE_API_URL` in Vercel environment variables to your Render backend URL.

---

## User Roles

| Role | Access | How Created |
|------|--------|-------------|
| **Super Admin** | Full platform control | Seeded on first startup via `SUPER_ADMIN_EMAIL` |
| **Organizer** | Create events, upload photos, manage clusters | Created by Super Admin in `/admin` panel |
| **Attendee** | Scan face, view gallery, download | Self-register via event access code at `/scan` |

### First login

1. Visit `http://localhost:8000/api/docs` (or your Render URL)
2. Use `POST /api/auth/login` with `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD`
3. Or login via the UI at `/login`

---

## API Endpoints Summary

```
POST /api/auth/login                    # Login (all roles)
POST /api/auth/attendee-join            # Attendee self-register with access code

GET  /api/admin/stats                   # [super_admin] System stats
GET  /api/admin/tenants                 # [super_admin] List organizations
POST /api/admin/tenants                 # [super_admin] Create organization
PATCH /api/admin/tenants/{id}/subscription  # [super_admin] Change plan

GET  /api/events/                       # [organizer] List events
POST /api/events/                       # [organizer] Create event
GET  /api/events/{id}                   # [organizer] Event detail

POST /api/photos/events/{id}/upload     # [organizer] Bulk photo upload (async)
POST /api/photos/events/{id}/batches    # [organizer] Start one durable upload batch
POST /api/photos/batches/{id}/seal      # [organizer] Close upload intake for a batch
POST /api/photos/events/{id}/reprocess-faces # [organizer] Re-embed all originals safely
GET  /api/photos/events/{id}            # [organizer] List photos + status

GET  /api/processing/snapshot           # [organizer/admin] Scoped live-processing snapshot
WS   /api/processing/ws                 # [organizer/admin] 1-second progress/resource stream

POST /api/faces/consent                 # [attendee] Record biometric consent
POST /api/faces/events/{id}/scan        # [attendee] Selfie scan → matched photos
DELETE /api/faces/scans/{scan_id}       # [attendee] Erase selfie data (GDPR)
GET  /api/faces/events/{id}/clusters    # [organizer] List face clusters
PATCH /api/faces/events/{id}/clusters/{cluster_id} # [organizer] Name a person
POST /api/faces/clusters/merge          # [organizer] Merge two clusters
POST /api/faces/events/{id}/recluster   # [organizer] Rebuild constrained People groups

POST /api/downloads/zip                 # [attendee] Stream ZIP of selected photos
```

The WebSocket expects `{ "type": "auth", "token": "<JWT>" }` as its first
message. Organizers receive only their organization’s running batches; super
admins receive platform totals. CPU is application process-tree utilization.
GPU utilization is device-wide and is reported as unavailable when NVML or a
GPU worker is not present. PostgreSQL owns exact counts; Redis is used only for
short rolling throughput windows and expiring worker heartbeats.

---

## Subscription Plans

| Plan | Events/mo | Photos/event | Storage | Price |
|------|-----------|-------------|---------|-------|
| Starter | 1 | 1,000 | 5 GB | Free |
| Pro | 5 | 5,000 | 50 GB | $29/mo |
| Enterprise | Unlimited | 20,000 | 500 GB | Custom |

Plans are assigned by the Super Admin. Organizers cannot self-upgrade.

---

## Privacy & Compliance

- Face **embeddings** (not images) are stored as the biometric reference
- Explicit consent is required before any selfie scan
- Users can delete their embedding at any time (right to erasure — GDPR / DPDP Act 2023)
- All photo access is via time-limited presigned URLs (no public buckets)
- All access is audit-logged
