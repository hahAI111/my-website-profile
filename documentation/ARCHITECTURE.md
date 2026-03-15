# Architecture — Aimee's Portfolio

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        Internet                             │
│                  (https://aimeelan.azurewebsites.net)       │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│              Azure App Service (Linux, Python 3.14)          │
│  ┌────────────────────────────────────────────────────────┐  │
│  │   gunicorn  →  Flask (app.py)                          │  │
│  │                                                        │  │
│  │   Routes:                                              │  │
│  │   GET  /             → verify.html / index.html        │  │
│  │   GET  /blog         → blog listing                    │  │
│  │   GET  /blog/<slug>  → individual post                 │  │
│  │   GET  /projects     → GitHub project showcase         │  │
│  │   GET  /admin        → admin dashboard (login req.)    │  │
│  │                        (incl. Redis cache monitoring)   │  │
│  │   POST /api/verify   → validate email → insert visitor │  │
│  │   POST /api/pageview → record page view analytics      │  │
│  │   POST /api/track    → log click event                 │  │
│  │   POST /api/contact  → save message → send email       │  │
│  │   GET  /api/posts    → blog posts (pagination, tags)   │  │
│  │   GET  /api/projects → synced GitHub repos             │  │
│  │   POST /api/admin/*  → login, stats, export, retention │  │
│  └────────────┬──────────────────┬────────────────────────┘  │
│               │  VNet Integration│                            │
└───────────────┼──────────────────┼────────────────────────────┘
                │                  │
        ┌───────▼───────┐  ┌──────▼────────┐
        │   PostgreSQL   │  │  Redis Cache   │
        │  (Flexible     │  │  (Basic SKU)   │
        │   Server)      │  │               │
        │  Port 5432     │  │  Port 6380    │
        │  SSL required  │  │  SSL required │
        └───────────────┘  └───────────────┘
             ▲                    ▲
             │                    │
         Private Endpoint      Private Endpoint
         (VNet internal)       (VNet internal)

                                        ┌──────────────┐
                Flask send_notification ─►  Gmail SMTP   │
                                        │ smtp.gmail.com│
                                        │   Port 587    │
                                        └──────────────┘
```

## Azure Resource List

| Resource | Name | Type | Region | Purpose |
|----------|------|------|--------|---------|
| Web App | `aimeelan` | App Service (Linux, Python 3.14) | Canada Central | Hosts Flask application |
| PostgreSQL | `aimeelan-server` | Flexible Server | Canada Central | Persistent storage |
| Database | `aimeelan-database` | PostgreSQL DB | — | App database on the above server |
| Redis | `aimee-cache` | Azure Cache for Redis (Basic) | Canada Central | Response caching |
| VNet | `vnet-zqopjmgp` | Virtual Network | Canada Central | Private networking |
| Resource Group | `aimee-test-env` | — | — | Contains all resources |

## Networking Architecture

```
┌─── Azure VNet (vnet-zqopjmgp) ─────────────────────────┐
│                                                          │
│  ┌─ Subnet: web ──────────────────────────────────────┐  │
│  │  App Service (VNet Integration)                    │  │
│  │  ← Outbound traffic routed through VNet            │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─ Subnet: db ───────────────────────────────────────┐  │
│  │  PostgreSQL Flexible Server (Private Endpoint)     │  │
│  │  ← Only accepts VNet-internal connections          │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─ Subnet: redis ────────────────────────────────────┐  │
│  │  Redis Cache (Private Endpoint)                    │  │
│  │  ← Only accepts VNet-internal connections          │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Key Concepts:**
- **VNet Integration (outbound)**: App Service outbound traffic (to database, to Redis) goes through VNet internal network, not the public internet
- **Private Endpoint (inbound)**: PostgreSQL and Redis are exposed within the VNet via Private Endpoints; external networks cannot directly access them
- **Only the Web App is publicly exposed**: Only `aimeelan.azurewebsites.net` is internet-facing (with Azure-managed SSL)

---

## Database Design (PostgreSQL)

### Tables

#### `visitors` — Visitor Information
Records every visitor who passes through the verification page.

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | Auto-increment ID |
| `name` | TEXT | Visitor's name |
| `email` | TEXT | Visitor's email (validated, blocked domains rejected) |
| `verified` | INTEGER | 1 = verified |
| `token` | TEXT | Unique session token |
| `created_at` | TIMESTAMP | Registration time |

#### `click_logs` — Click Tracking
Records every click by verified users on page elements (e.g., clicking "About" in the nav bar, LinkedIn link, etc.).

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | Auto-increment ID |
| `visitor_id` | INTEGER FK → visitors(id) | Who clicked |
| `element` | TEXT | What was clicked (e.g. `nav-about`, `social-linkedin`) |
| `page` | TEXT | Which page they were on |
| `clicked_at` | TIMESTAMP | When they clicked |

#### `messages` — Contact Messages
Messages sent by visitors to the site owner via the Contact form.

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | Auto-increment ID |
| `visitor_id` | INTEGER FK → visitors(id) | Who sent it |
| `name` | TEXT | Sender name |
| `email` | TEXT | Sender email |
| `message` | TEXT | Message content |
| `sent_at` | TIMESTAMP | When it was sent |

#### `page_views` — Page View Tracking
Records detailed information for every page visit, used for visitor behavior analysis.

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | Auto-increment ID |
| `visitor_id` | INTEGER FK → visitors(id) | Who viewed (nullable for anonymous) |
| `page` | TEXT | URL path visited |
| `referrer` | TEXT | Where they came from |
| `user_agent` | TEXT | Browser/device info |
| `ip_hash` | TEXT | SHA-256 hash of IP (privacy) |
| `duration_sec` | INTEGER | Time spent on page |
| `screen_width` | INTEGER | Screen width in px (device classification) |
| `created_at` | TIMESTAMP | When the page was viewed |

#### `visitor_sessions` — Visitor Sessions
Tracks the lifecycle of a single visit session.

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | Auto-increment ID |
| `visitor_id` | INTEGER FK → visitors(id) | Session owner |
| `session_token` | TEXT UNIQUE | Random session identifier |
| `started_at` | TIMESTAMP | Session start |
| `ended_at` | TIMESTAMP | Last activity |
| `page_count` | INTEGER | Pages viewed in session |

#### `posts` — Blog Posts
Stores blog posts in Markdown format.

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | Auto-increment ID |
| `slug` | TEXT UNIQUE | URL-friendly identifier |
| `title` | TEXT | Post title |
| `summary` | TEXT | Short description |
| `content` | TEXT | Full Markdown content |
| `status` | TEXT | `published` or `draft` |
| `views` | INTEGER | View counter |
| `published_at` | TIMESTAMP | Publish date |
| `updated_at` | TIMESTAMP | Last edit |
| `created_at` | TIMESTAMP | Creation time |

#### `tags` — Tags

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | Auto-increment ID |
| `name` | TEXT UNIQUE | Tag name (e.g. `Azure`, `Python`) |

#### `post_tags` — Post-Tag Association (Many-to-Many)

| Column | Type | Description |
|--------|------|-------------|
| `post_id` | INTEGER FK → posts(id) | Post reference |
| `tag_id` | INTEGER FK → tags(id) | Tag reference |

#### `projects` — GitHub Project Showcase
Repository information synced from the GitHub API.

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | Auto-increment ID |
| `github_repo` | TEXT UNIQUE | Full repo name (e.g. `hahAI111/aimeewebpage`) |
| `name` | TEXT | Repo name |
| `description` | TEXT | Repo description |
| `language` | TEXT | Primary language |
| `stars` | INTEGER | Star count |
| `forks` | INTEGER | Fork count |
| `open_issues` | INTEGER | Open issue count |
| `homepage` | TEXT | Homepage URL |
| `last_commit_at` | TIMESTAMP | Last push time |
| `featured` | BOOLEAN | Highlighted project |
| `synced_at` | TIMESTAMP | Last sync time |

### Entity Relationship

```
visitors (1) ──→ (N) click_logs
    │
    ├──────────→ (N) messages
    │
    ├──────────→ (N) page_views
    │
    └──────────→ (N) visitor_sessions

posts (N) ←──→ (N) tags    (via post_tags)

projects (standalone, synced from GitHub API)
```

Each visitor can have multiple click_logs, messages, page_views, and visitor_sessions.  
Posts and tags have a many-to-many relationship via the post_tags junction table.  
Projects are independent of the visitor system, synced via admin-triggered GitHub API calls.

---

## Redis Cache — Role & Strategy

Redis serves as a **cache layer for read-heavy API responses**, reducing unnecessary database queries.

### Workflow

```
GET /api/admin/stats
        │
        ▼
  cache_get("stats:overview")
        │
   ┌────┴────┐
   │ Cached?  │
   └────┬────┘
    Yes │      No
    ┌───▼──┐  ┌──▼────────────┐
    │Return │  │Query PostgreSQL│
    │cached │  │  COUNT(*)×3   │
    │data   │  │  + latest 10  │
    └──────┘  └──────┬────────┘
                     │
                     ▼
              cache_set("stats:overview", data, ttl=60)
                     │
                     ▼
                  Return data
```

### Cache Invalidation
- **TTL**: Automatically expires after 60 seconds
- **Active clearing**: When a new message is submitted, `cache_delete("stats:*")` clears all stats caches
- **Degradation**: If Redis is unreachable, queries go directly to the database without affecting functionality

### Why Redis Instead of In-Memory Cache?
- Azure App Service may have multiple worker processes; in-memory cache isn't shared across them
- Redis is an independent service — all workers share the same cache
- Cache persists across App Service restarts (until TTL expiration)

---

## Data Flow — Complete User Journey

```
1. User visits https://aimeelan.azurewebsites.net
   │
   ▼
2. Flask checks session → not verified → returns verify.html
   │
   ▼
3. User enters Name + Email → POST /api/verify
   │
   ├── Email format validation (regex)
   ├── Blocked domain check (BLOCKED_DOMAINS)
   ├── Insert into PostgreSQL visitors table
   └── Set session: verified=True, visitor_id, name, email
   │
   ▼
4. Page redirects to / → Flask checks session → verified → returns index.html
   │
   ▼
5. script.js auto-sends POST /api/pageview (page, referrer, screen width, UA)
   → Writes to page_views table + creates/updates visitor_sessions
   │
   ▼
6. User browses pages; each click on elements with data-track attribute
   → script.js sends POST /api/track → writes to click_logs table
   │
   ▼
7. User can visit /blog → browse blog posts (5 pre-seeded articles about Azure AI Support)
   → GET /api/posts supports tag filtering and pagination
   → GET /api/posts/<slug> returns full Markdown content, rendered by marked.js on frontend
   │
   ▼
8. User can visit /projects → view GitHub-synced projects
   → GET /api/projects returns project list (language, stars, forks, etc.)
   │
   ▼
9. User fills out Contact form → POST /api/contact
   ├── Writes to messages table
   ├── Clears Redis cache (stats:*)
   └── Sends Gmail notification to site owner
   │
   ▼
10. Site owner visits /admin → logs in to view full data dashboard
    ├── POST /api/admin/login (bcrypt password verification)
    ├── GET /api/admin/stats → KPI cards + 6 Chart.js charts
    ├── GET /api/admin/visitors → paginated visitor list + domain filtering
    ├── GET /api/admin/retention → retention analysis (Day 0/1/7/30 cohorts)
    ├── GET /api/admin/export/<table> → CSV download
    └── POST /api/projects/sync → one-click GitHub repo sync
```

---

## Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `AZURE_POSTGRESQL_CONNECTIONSTRING` | Azure auto-set (Connection Strings) | PostgreSQL connection info |
| `REDISCACHECONNSTR_azure_redis_cache` | Azure auto-set (Connection Strings) | Redis connection info |
| `OWNER_EMAIL` | Manual (App Settings) | Email to receive notifications |
| `SMTP_SERVER` | Manual (App Settings) | `smtp.gmail.com` |
| `SMTP_PORT` | Manual (App Settings) | `587` |
| `SMTP_USER` | Manual (App Settings) | Gmail address |
| `SMTP_PASS` | Manual (App Settings) | Gmail App Password (16-char) |
| `SECRET_KEY` | Manual (App Settings) | Flask session encryption key |
| `ADMIN_USER` | Manual (App Settings) | Admin login username (default: `admin`) |
| `ADMIN_PASS` or `ADMIN_PASS_HASH` | Manual (App Settings) | Admin password (plain text or bcrypt hash) |
| `GITHUB_USERNAME` | Manual (App Settings) | GitHub user for project sync (default: `hahAI111`) |
| `GITHUB_TOKEN` | Manual (App Settings) | GitHub PAT for higher API rate limit (optional) |

**Note:** Azure Connection Strings are injected as environment variables with prefixes:
- Custom type → `CUSTOMCONNSTR_` prefix
- Redis type → `REDISCACHECONNSTR_` prefix

Our code checks both prefixed and unprefixed names for compatibility.

---

## CI/CD Pipeline

```
git push origin main
        │
        ▼
GitHub Actions (.github/workflows/main_aimeelan.yml)
        │
        ├── 1. Checkout code
        ├── 2. Setup Python 3.14
        ├── 3. pip install -r requirements.txt (build verification)
        ├── 4. Upload artifact (exclude venv)
        │
        ▼
        ├── 5. Azure Login (OIDC, federated credential)
        └── 6. Deploy to Azure App Service (Oryx build)
                │
                ▼
            Oryx runs pip install again on Azure
                │
                ▼
            gunicorn --bind=0.0.0.0:8000 app:app
                │
                ▼
            Site live at https://aimeelan.azurewebsites.net
```

---

## Security Design

### Password Hashing — Why bcrypt?

Admin passwords are stored as **bcrypt hashes**, not plain text or simple SHA-256.

| Approach | Problem |
|----------|---------|
| Plain text | Any database breach = all passwords exposed |
| SHA-256 | Fast to compute → vulnerable to brute-force (billions of guesses/sec) |
| bcrypt | Intentionally slow (cost factor) → brute-force becomes impractical |

How bcrypt works:
1. **Salt**: Generates a unique random salt per password (stored in the hash itself)
2. **Cost factor**: `bcrypt.gensalt(rounds=12)` = $2^{12}$ = 4,096 iterations of the Blowfish cipher
3. **Output**: `$2b$12$salt...hash` — includes algorithm version, cost, salt, and hash in one string
4. **Verification**: `bcrypt.checkpw(password, hash)` is timing-safe (prevents timing attacks)

```python
# Storing (at setup):
hash = bcrypt.hashpw(b"password", bcrypt.gensalt())
# Verifying (at login):
bcrypt.checkpw(b"password", stored_hash)  # → True/False
```

### Database Connections — Why No Connection Pool?

The current design creates a **new `psycopg2.connect()` per request** rather than using a connection pool:

```python
conn = psycopg2.connect(DATABASE_URL)
# ... execute queries ...
conn.close()
```

**Why this works for our scale:**
- Azure PostgreSQL Flexible Server handles connection management efficiently
- Our traffic volume (personal portfolio) doesn't warrant pooling overhead
- Each request opens → queries → closes cleanly, avoiding connection leaks

**When to add pooling (psycopg2.pool or PgBouncer):**
- If concurrent users exceed ~50 simultaneous requests
- If connection setup time becomes a measurable bottleneck (>50ms)
- If Azure reports "too many connections" errors

This is a deliberate trade-off: **simplicity over premature optimization.**
