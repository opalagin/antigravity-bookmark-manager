# Railway Deployment — AI Bookmark Manager

**Project:** `ai-bookmark-manager`  
**Deployed:** April 26, 2026  
**Railway Project URL:** https://railway.com/project/905ede83-5765-4385-a895-9847de8b0c78

---

## Live Endpoints

| Resource | URL |
|---|---|
| **Search Backend API** | https://search-backend-production.up.railway.app |
| **Health Check** | https://search-backend-production.up.railway.app/ |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│               Railway Project (production)          │
│                                                     │
│  ┌──────────────────────┐   ┌─────────────────────┐ │
│  │    search-backend    │   │      Postgres        │ │
│  │                      │◄──│   (pgvector-pg17)   │ │
│  │  Docker Hub image:   │   │                     │ │
│  │  apalagin/           │   │  postgres.railway   │ │
│  │  ai-bookmanager-     │   │  .internal:5432     │ │
│  │  backend:latest      │   │                     │ │
│  │                      │   │  Extensions:        │ │
│  │  Port: 8000          │   │  • pgvector (v384)  │ │
│  │  HTTPS: ✅ (Railway) │   │  • hnsw index       │ │
│  └──────────────────────┘   └─────────────────────┘ │
│             │                                        │
└─────────────┼────────────────────────────────────────┘
              │ HTTPS (TLS managed by Railway)
              ▼
   Browser Extension / Plugin
```

---

## Services

### 1. Search Backend
- **Source:** Docker Hub image `apalagin/ai-bookmanager-backend:latest`
- **Image digest (deployed):** `sha256:0a687b14a9bea9c2dc03d5629117006947d54f7eca104b8740605c7fe8de1fbd`
- **Runtime:** Python 3.11 / FastAPI / Uvicorn on port 8000
- **HTTPS domain:** Automatically provisioned by Railway (`*.up.railway.app`)
- **Restart policy:** On failure, max 10 retries

### 2. Postgres Database
- **Type:** Railway managed Postgres (Hobby plan)
- **Extensions:** `pgvector` (vector similarity search, VECTOR(384) dimensions)
- **Internal hostname:** `postgres.railway.internal:5432` (private network, not public)
- **Public proxy:** `nozomi.proxy.rlwy.net:49749` (for admin tooling only)

---

## Environment Variables (search-backend)

| Variable | Value | Notes |
|---|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | Auto-resolved from Postgres plugin |
| `OPENAI_API_KEY` | `sk-proj-...` | Set via Railway dashboard — never in git |
| `PORT` | `8000` | Matches Dockerfile CMD |

> **Security:** No secrets exist in source code or git history. All sensitive values are injected at runtime by Railway.

---

## Database Schema

Initialized via `Railway/setup_railway_db.py` (idempotent — safe to re-run).

```sql
-- Vector similarity search extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Bookmark metadata store
CREATE TABLE bookmarks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    content_markdown TEXT,
    tags TEXT[],
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_user_url UNIQUE (user_id, url)
);

-- Chunked embeddings for semantic search
CREATE TABLE bookmark_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bookmark_id UUID REFERENCES bookmarks(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(384)           -- all-MiniLM-L6-v2 dimensions
);
CREATE INDEX embedding_idx ON bookmark_embeddings
    USING hnsw (embedding vector_cosine_ops);  -- fast ANN search

-- Pilot Mode access control
CREATE TABLE allowed_users (
    email TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

**Seeded allowed users:** `alex.palagin@gmail.com`

---

## API Endpoints

| Method | Path | Auth | Rate Limit | Description |
|---|---|---|---|---|
| `GET` | `/` | None | — | Health check |
| `POST` | `/bookmarks` | Google OAuth | 10/min | Ingest a bookmark |
| `GET` | `/recent` | Google OAuth | — | Fetch recent bookmarks |
| `POST` | `/search` | Google OAuth | 60/min | Semantic vector search |
| `POST` | `/chat` | Google OAuth | 20/min | RAG chat over bookmarks |

**Authentication:** All protected endpoints validate a Google OAuth access token via `https://www.googleapis.com/oauth2/v3/userinfo`. Users must be in the `allowed_users` table (Pilot Mode).

---

## Code Changes Made for Railway Compatibility

### `Search Backend/database.py`
Supports both Railway's single `DATABASE_URL` and the local Docker Compose `POSTGRES_*` variables:
```python
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    # Railway emits postgres:// — asyncpg needs postgresql+asyncpg://
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    # Fallback: assemble from individual POSTGRES_* vars (Docker Compose)
    DATABASE_URL = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"
```

### `Search Backend/main.py`
FastAPI lifespan now runs idempotent schema init on every startup — no volume-mounted `init.sql` needed:
```python
@asynccontextmanager
async def lifespan(app):
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE TABLE IF NOT EXISTS bookmarks (...)"))
        await conn.execute(text("CREATE TABLE IF NOT EXISTS bookmark_embeddings (...)"))
        await conn.execute(text("CREATE TABLE IF NOT EXISTS allowed_users (...)"))
    yield
    await engine.dispose()
```

### `Search Backend/railway.json`
Minimal Railway service config (deploy-only, no build — image comes from Docker Hub):
```json
{
  "deploy": {
    "startCommand": "uvicorn main:app --host 0.0.0.0 --port $PORT",
    "healthcheckPath": "/",
    "healthcheckTimeout": 120,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

---

## Utility Scripts

### `Railway/setup_railway_db.py`
One-shot script to initialize the schema and seed `allowed_users` against the Railway Postgres public proxy. Safe to re-run (all statements are idempotent).

```bash
python Railway/setup_railway_db.py
```

### `Railway/seed_allowed_users.py`
Lightweight script to add new allowed users to an already-initialized database. Set `PILOT_MODE_EMAILS` env var (comma-separated) to override the default list.

```bash
$env:DATABASE_URL="postgresql://postgres:<pass>@nozomi.proxy.rlwy.net:49749/railway"
python Railway/seed_allowed_users.py
```

---

## Updating the Deployment

When new code changes are ready:

```bash
# 1. Build the updated Docker image locally
docker build -t apalagin/ai-bookmanager-backend:latest "Search Backend/"

# 2. Push to Docker Hub
docker push apalagin/ai-bookmanager-backend:latest

# 3. Trigger a redeploy in Railway dashboard
#    → search-backend → Deployments → Deploy (with latest tag)
```

> Railway does **not** auto-pull on push. A manual redeploy in the dashboard is required to pick up a new image digest.

---

## Pointing the Plugin to Railway

Update the extension's `API_BASE_URL` constant to:

```
https://search-backend-production.up.railway.app
```

The endpoint is HTTPS-only, TLS-terminated by Railway's edge, with no additional configuration needed.

---

## Security Posture

| Control | Status |
|---|---|
| HTTPS / TLS | ✅ Railway-managed, auto-renewed |
| Secrets in git | ✅ None — `.env` is gitignored |
| API key exposure | ✅ Set via Railway vars only |
| Postgres public access | ✅ Internal-only (`railway.internal`); public proxy for admin |
| Auth on all endpoints | ✅ Google OAuth + `allowed_users` allowlist (Pilot Mode) |
| Rate limiting | ✅ SlowAPI: 10–60 req/min per endpoint |
| CORS | ⚠️ `allow_origins=["*"]` — acceptable for browser extension use |
