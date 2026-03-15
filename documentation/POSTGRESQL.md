# PostgreSQL Database — Usage & Monitoring Guide

This project uses **Azure Database for PostgreSQL Flexible Server** (instance: `aimeelan-server`, database: `aimeelan-database`)
as the persistent storage layer, managing all business data including visitors, blog, projects, and analytics.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Connection Configuration](#connection-configuration)
  - [Environment Variables](#environment-variables)
  - [Connection String Parsing](#connection-string-parsing)
  - [Connection Method](#connection-method)
- [Database Schema](#database-schema)
  - [ER Diagram](#er-diagram)
  - [Table Details](#table-details)
  - [Index Design](#index-design)
- [SQL Operations by Module](#sql-operations-by-module)
  - [Visitor Registration](#1-visitor-registration)
  - [Page View Tracking](#2-page-view-tracking)
  - [Click Tracking](#3-click-tracking)
  - [Contact Messages](#4-contact-messages)
  - [Blog Posts](#5-blog-posts)
  - [Tag System](#6-tag-system)
  - [GitHub Projects](#7-github-projects)
  - [Admin Analytics Dashboard](#8-admin-analytics-dashboard)
  - [Paginated Visitor Query](#9-paginated-visitor-query)
  - [CSV Data Export](#10-csv-data-export)
  - [Retention Analysis](#11-retention-analysis)
- [Data Seeding](#data-seeding)
- [Connection Management Pattern](#connection-management-pattern)
- [Azure Portal Monitoring](#azure-portal-monitoring)
  - [Key Metrics](#key-metrics)
  - [Setting Up Metrics Charts](#setting-up-metrics-charts)
  - [Alert Configuration](#alert-configuration)
- [Common Maintenance Commands](#common-maintenance-commands)
  - [Connecting to the Database](#connecting-to-the-database)
  - [Data Queries](#data-queries)
  - [Performance Diagnostics](#performance-diagnostics)
  - [Data Cleanup](#data-cleanup)
- [Performance Optimization Notes](#performance-optimization-notes)
- [FAQ](#faq)

---

## Architecture Overview

```
Flask API
  │
  ├── get_db()  ──→  psycopg2.connect(DATABASE_URL, sslmode="require")
  │                       │
  │                       └──→ Azure PostgreSQL Flexible Server
  │                            ├── aimeelan-database
  │                            │     ├── visitors          (visitor table)
  │                            │     ├── click_logs        (click log table)
  │                            │     ├── messages          (contact messages)
  │                            │     ├── page_views        (page view table)
  │                            │     ├── visitor_sessions  (session table)
  │                            │     ├── posts             (blog posts)
  │                            │     ├── tags              (tag table)
  │                            │     ├── post_tags         (post-tag junction)
  │                            │     └── projects          (GitHub projects)
  │                            └── SSL encrypted connection (port 5432)
  │
  └── init_db()  ──→  CREATE TABLE IF NOT EXISTS (auto-creates tables on startup)
```

---

## Connection Configuration

### Environment Variables

Azure App Service automatically injects the PostgreSQL connection string. The code reads by priority:

| Variable Name | Priority | Description |
|---|---|---|
| `AZURE_POSTGRESQL_CONNECTIONSTRING` | 1 (highest) | Manually configured in App Service environment variables |
| `CUSTOMCONNSTR_AZURE_POSTGRESQL_CONNECTIONSTRING` | 2 | Auto-prefixed by Azure Service Connector |
| Local default | 3 | `host=localhost dbname=portfoliodb user=postgres password=postgres` |

### Connection String Parsing

Azure provides the connection string in **ADO.NET format** (semicolon-delimited):
```
Server=aimeelan-server.postgres.database.azure.com;Database=aimeelan-database;Port=5432;User Id=xxxxx;Password=xxxxx;
```

The `_parse_pg_conn()` function converts it to **psycopg2 (libpq) format** (space-delimited):
```
host=aimeelan-server.postgres.database.azure.com dbname=aimeelan-database user=xxxxx password=xxxxx
```

```python
def _parse_pg_conn(raw):
    if not raw or raw.startswith("host="):    # Already libpq format, return as-is
        return raw
    parts = dict(p.split("=", 1) for p in raw.split(";") if "=" in p)
    return (
        f"host={parts.get('Server','')} "
        f"dbname={parts.get('Database','')} "
        f"user={parts.get('User Id','')} "
        f"password={parts.get('Password','')}"
    )
```

### Connection Method

```python
def get_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    return conn
```

- **psycopg2**: The most mature PostgreSQL driver for Python
- **sslmode="require"**: Enforces SSL encryption; required by Azure PostgreSQL
- Each request gets a new connection, closed after use (no connection pooling)

---

## Database Schema

### ER Diagram

```
visitors (1) ───< (N) click_logs
    │
    ├───────────< (N) messages
    │
    ├───────────< (N) page_views
    │
    └───────────< (N) visitor_sessions

posts (1) ───< (N) post_tags >── (1) tags

projects (standalone table, no foreign key relationships)
```

### Table Details

#### 1. `visitors` — Visitor Table

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | Auto-increment primary key |
| `name` | TEXT | NOT NULL | Visitor name |
| `email` | TEXT | NOT NULL | Visitor email |
| `verified` | INTEGER | DEFAULT 0 | Verification status (1=verified) |
| `token` | TEXT | | Verification token |
| `created_at` | TIMESTAMP | DEFAULT NOW() | Registration time |

**Purpose**: Visitor information collected from the entry verification page (verify.html).

#### 2. `click_logs` — Click Log Table

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | Auto-increment primary key |
| `visitor_id` | INTEGER | REFERENCES visitors(id) | Associated visitor |
| `element` | TEXT | NOT NULL | Clicked button/link identifier (e.g. `nav-blog`) |
| `page` | TEXT | | Page where the click occurred |
| `clicked_at` | TIMESTAMP | DEFAULT NOW() | Click time |

**Purpose**: All clickable elements marked with the `data-track` attribute on the frontend.

#### 3. `messages` — Contact Message Table

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | Auto-increment primary key |
| `visitor_id` | INTEGER | REFERENCES visitors(id) | Associated visitor |
| `name` | TEXT | NOT NULL | Sender name |
| `email` | TEXT | NOT NULL | Sender email |
| `message` | TEXT | NOT NULL | Message content |
| `sent_at` | TIMESTAMP | DEFAULT NOW() | Send time |

**Purpose**: Messages submitted via the Contact form; also triggers SMTP email notification.

#### 4. `page_views` — Page View Table

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | Auto-increment primary key |
| `visitor_id` | INTEGER | REFERENCES visitors(id) | Associated visitor (nullable) |
| `page` | TEXT | NOT NULL | Page path (e.g. `/`, `/blog`) |
| `referrer` | TEXT | | Source page URL |
| `user_agent` | TEXT | | Browser UA string (truncated to 500 chars) |
| `ip_hash` | TEXT | | SHA-256 hash of IP address (privacy protection) |
| `duration_sec` | INTEGER | DEFAULT 0 | Time spent on page (seconds) |
| `screen_width` | INTEGER | | Screen width (for device type analysis) |
| `created_at` | TIMESTAMP | DEFAULT NOW() | View time |

**Purpose**: The core analytics data source — powers the admin dashboard's PV trends, device distribution, top pages, and retention analysis.

#### 5. `visitor_sessions` — Visitor Session Table

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | Auto-increment primary key |
| `visitor_id` | INTEGER | REFERENCES visitors(id) | Associated visitor |
| `session_token` | TEXT | UNIQUE | Session token (correlates multiple PVs in one visit) |
| `started_at` | TIMESTAMP | DEFAULT NOW() | Session start time |
| `ended_at` | TIMESTAMP | | Session end time |
| `page_count` | INTEGER | DEFAULT 0 | Pages viewed in this session |

**Purpose**: Track visit depth (how many pages viewed, how long they stayed).

#### 6. `posts` — Blog Post Table

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | Auto-increment primary key |
| `slug` | TEXT | UNIQUE NOT NULL | URL-friendly identifier (e.g. `azure-openai-service-troubleshooting-guide`) |
| `title` | TEXT | NOT NULL | Post title |
| `summary` | TEXT | | Summary |
| `content` | TEXT | NOT NULL | Markdown body |
| `status` | TEXT | DEFAULT 'published' | Status: `published` / `draft` |
| `views` | INTEGER | DEFAULT 0 | View count |
| `published_at` | TIMESTAMP | DEFAULT NOW() | Publish date |
| `updated_at` | TIMESTAMP | DEFAULT NOW() | Last update |
| `created_at` | TIMESTAMP | DEFAULT NOW() | Creation date |

**Purpose**: Core table for the blog CMS. The `slug` is used for URL routing (`/blog/azure-openai-...`).

#### 7. `tags` — Tag Table

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | Auto-increment primary key |
| `name` | TEXT | UNIQUE NOT NULL | Tag name (e.g. `Azure`, `Python`) |

#### 8. `post_tags` — Post-Tag Junction Table

| Column | Type | Constraint | Description |
|---|---|---|---|
| `post_id` | INTEGER | REFERENCES posts(id) ON DELETE CASCADE | Post ID |
| `tag_id` | INTEGER | REFERENCES tags(id) ON DELETE CASCADE | Tag ID |
| | | PRIMARY KEY (post_id, tag_id) | Composite primary key |

**Relationship**: Many-to-many (a post can have multiple tags; a tag can belong to multiple posts). `ON DELETE CASCADE` ensures junction records are cleaned up when posts/tags are deleted.

#### 9. `projects` — GitHub Project Table

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | Auto-increment primary key |
| `github_repo` | TEXT | UNIQUE | Full repo name (e.g. `hahAI111/aimeewebpage`) |
| `name` | TEXT | NOT NULL | Repository name |
| `description` | TEXT | | Repository description |
| `language` | TEXT | | Primary programming language |
| `stars` | INTEGER | DEFAULT 0 | Star count |
| `forks` | INTEGER | DEFAULT 0 | Fork count |
| `open_issues` | INTEGER | DEFAULT 0 | Open issue count |
| `homepage` | TEXT | | Project homepage URL |
| `last_commit_at` | TIMESTAMP | | Last commit time |
| `featured` | BOOLEAN | DEFAULT FALSE | Whether to highlight |
| `synced_at` | TIMESTAMP | DEFAULT NOW() | Last sync time |

**Purpose**: Repository data synced via GitHub API. `ON CONFLICT (github_repo) DO UPDATE` implements upsert.

### Index Design

```sql
CREATE INDEX idx_pv_visitor       ON page_views(visitor_id);  -- Query PVs by visitor
CREATE INDEX idx_pv_created       ON page_views(created_at);  -- Query PVs by time range (trend charts)
CREATE INDEX idx_click_time       ON click_logs(clicked_at);  -- Query clicks by time (trend analysis)
CREATE INDEX idx_visitors_created ON visitors(created_at);    -- Query visitors by time (trend charts)
CREATE INDEX idx_posts_slug       ON posts(slug);             -- Query posts by slug (URL routing)
CREATE INDEX idx_posts_status     ON posts(status);           -- Filter by status (published/draft)
```

**Design principles**:
- `page_views` is the highest-volume table; `visitor_id` and `created_at` indexes cover analytics and retention queries
- `posts.slug` index ensures O(1) lookup for post detail pages
- All indexes use `CREATE INDEX IF NOT EXISTS` for restart safety

---

## SQL Operations by Module

### 1. Visitor Registration

**Trigger**: `POST /api/verify`

```sql
INSERT INTO visitors (name, email, verified, token)
VALUES (%s, %s, 1, %s)
RETURNING id;
```

- `RETURNING id`: PostgreSQL feature — returns the auto-increment ID immediately after insert (avoids an extra query)
- `verified = 1`: Marked as verified directly
- `token`: Random token (`secrets.token_urlsafe(32)`), reserved for future email verification

**Write frequency**: Once per new visitor

### 2. Page View Tracking

**Trigger**: `POST /api/pageview` (frontend `script.js` sends automatically on page load and `beforeunload`)

```sql
-- Record page view
INSERT INTO page_views (visitor_id, page, referrer, user_agent, ip_hash, duration_sec, screen_width)
VALUES (%s, %s, %s, %s, %s, %s, %s);

-- Update existing session
UPDATE visitor_sessions
SET page_count = page_count + 1, ended_at = NOW()
WHERE session_token = %s;

-- Or create new session
INSERT INTO visitor_sessions (visitor_id, session_token, page_count)
VALUES (%s, %s, 1);
```

**Privacy protection**:
- `ip_hash`: IP address is SHA-256 hashed — raw IPs are never stored
- `user_agent`: Truncated to first 500 characters to prevent oversized string attacks

**Write frequency**: 1–2 writes per page view (highest frequency write operation)

### 3. Click Tracking

**Trigger**: `POST /api/track`

```sql
INSERT INTO click_logs (visitor_id, element, page)
VALUES (%s, %s, %s);
```

**Write frequency**: Each click on a `data-track` attributed element on the frontend

### 4. Contact Messages

**Trigger**: `POST /api/contact`

```sql
INSERT INTO messages (visitor_id, name, email, message)
VALUES (%s, %s, %s, %s);
```

**Write frequency**: Low (manually submitted by visitors)

### 5. Blog Posts

**Post list**: `GET /api/posts?tag=Azure&page=1&per_page=10`

```sql
-- With tag filter
SELECT p.id, p.slug, p.title, p.summary, p.views, p.published_at::text as published_at
FROM posts p
JOIN post_tags pt ON p.id = pt.post_id
JOIN tags t ON pt.tag_id = t.id
WHERE p.status = 'published' AND t.name = %s
ORDER BY p.published_at DESC
LIMIT %s OFFSET %s;

-- Without tag filter
SELECT id, slug, title, summary, views, published_at::text as published_at
FROM posts WHERE status = 'published'
ORDER BY published_at DESC
LIMIT %s OFFSET %s;

-- Load tags for each post
SELECT t.name FROM tags t
JOIN post_tags pt ON t.id = pt.tag_id
WHERE pt.post_id = %s;

-- Total count for pagination
SELECT COUNT(*) as c FROM posts WHERE status = 'published';
```

**Post detail**: `GET /api/posts/<slug>`

```sql
SELECT id, slug, title, summary, content, views, status,
       published_at::text as published_at, updated_at::text as updated_at
FROM posts WHERE slug = %s;

-- Load tags
SELECT t.name FROM tags t
JOIN post_tags pt ON t.id = pt.tag_id
WHERE pt.post_id = %s;

-- Update view count
UPDATE posts SET views = views + 1 WHERE slug = %s;
```

**Notes**:
- `::text` casts TIMESTAMP to string for JSON serialization
- `LIMIT %s OFFSET %s`: Server-side pagination
- View count increments on every visit (even on cache hit, the UPDATE still runs)

### 6. Tag System

**Tag list**: `GET /api/tags`

```sql
SELECT t.name, COUNT(pt.post_id) as post_count
FROM tags t
LEFT JOIN post_tags pt ON t.id = pt.tag_id
LEFT JOIN posts p ON pt.post_id = p.id AND p.status = 'published'
GROUP BY t.name
HAVING COUNT(pt.post_id) > 0
ORDER BY post_count DESC;
```

**Note**: `HAVING COUNT > 0` filters out tags with no published posts.

### 7. GitHub Projects

**Read**: `GET /api/projects`

```sql
SELECT id, github_repo, name, description, language, stars, forks,
       open_issues, homepage, featured,
       last_commit_at::text as last_commit_at, synced_at::text as synced_at
FROM projects
ORDER BY featured DESC, stars DESC, last_commit_at DESC NULLS LAST;
```

**Sync (Upsert)**: `POST /api/projects/sync`

```sql
INSERT INTO projects (github_repo, name, description, language, stars, forks,
                      open_issues, homepage, last_commit_at, synced_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
ON CONFLICT (github_repo) DO UPDATE SET
    name=EXCLUDED.name, description=EXCLUDED.description, language=EXCLUDED.language,
    stars=EXCLUDED.stars, forks=EXCLUDED.forks, open_issues=EXCLUDED.open_issues,
    homepage=EXCLUDED.homepage, last_commit_at=EXCLUDED.last_commit_at, synced_at=NOW();
```

**Notes**:
- `ON CONFLICT ... DO UPDATE`: PostgreSQL's **Upsert** syntax — update if `github_repo` exists, insert otherwise
- `EXCLUDED`: References the rejected new values from the INSERT
- `NULLS LAST`: Repos without a last commit time sort to the end
- Sort priority: Featured > Stars > Last commit time

### 8. Admin Analytics Dashboard

**Trigger**: `GET /api/admin/stats` (requires admin login)

8 queries in total, returning complete analytics data:

```sql
-- 1. Total counts (KPI cards)
SELECT COUNT(*) as c FROM visitors;
SELECT COUNT(*) as c FROM click_logs;
SELECT COUNT(*) as c FROM messages;
SELECT COUNT(*) as c FROM page_views;
SELECT COUNT(*) as c FROM posts WHERE status = 'published';

-- 2. Last 30 days visitor trend (line chart)
SELECT DATE(created_at)::text as day, COUNT(*) as count
FROM visitors
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY DATE(created_at) ORDER BY day;

-- 3. Last 30 days PV trend (line chart)
SELECT DATE(created_at)::text as day, COUNT(*) as count
FROM page_views
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY DATE(created_at) ORDER BY day;

-- 4. Top 15 clicked elements (bar chart)
SELECT element, COUNT(*) as clicks
FROM click_logs GROUP BY element
ORDER BY clicks DESC LIMIT 15;

-- 5. Top 10 pages + average time spent
SELECT page, COUNT(*) as views,
       COALESCE(AVG(duration_sec)::int, 0) as avg_duration
FROM page_views GROUP BY page
ORDER BY views DESC LIMIT 10;

-- 6. Top 15 email domains (understand visitor companies)
SELECT SPLIT_PART(email, '@', 2) as domain, COUNT(*) as count
FROM visitors GROUP BY domain
ORDER BY count DESC LIMIT 15;

-- 7. Device type distribution (pie chart)
SELECT CASE
    WHEN screen_width IS NULL THEN 'Unknown'
    WHEN screen_width < 768  THEN 'Mobile'
    WHEN screen_width < 1024 THEN 'Tablet'
    ELSE 'Desktop'
END as device, COUNT(*) as count
FROM page_views GROUP BY device
ORDER BY count DESC;

-- 8. Recent messages + top posts
SELECT id, name, email, message, sent_at::text FROM messages ORDER BY sent_at DESC LIMIT 10;
SELECT slug, title, views, published_at::text FROM posts WHERE status='published' ORDER BY views DESC LIMIT 10;
```

**SQL techniques**:
- `DATE(created_at)`: Extract date portion for GROUP BY day
- `NOW() - INTERVAL '30 days'`: PostgreSQL time arithmetic
- `SPLIT_PART(email, '@', 2)`: Extract email domain
- `COALESCE(..., 0)`: NULL-safe default value
- `CASE WHEN`: Classify continuous data (screen_width) into discrete labels

### 9. Paginated Visitor Query

**Trigger**: `GET /api/admin/visitors?page=1&per_page=20&domain=microsoft.com`

```sql
-- With domain filter
SELECT id, name, email, created_at::text as created_at
FROM visitors WHERE email LIKE %s
ORDER BY created_at DESC LIMIT %s OFFSET %s;

SELECT COUNT(*) as c FROM visitors WHERE email LIKE %s;

-- Without filter
SELECT id, name, email, created_at::text as created_at
FROM visitors ORDER BY created_at DESC LIMIT %s OFFSET %s;

SELECT COUNT(*) as c FROM visitors;
```

**Note**: Domain filtering uses `LIKE '%@microsoft.com'` pattern matching.

### 10. CSV Data Export

**Trigger**: `GET /api/admin/export/<table>`

```sql
SELECT * FROM {table} ORDER BY id DESC LIMIT 5000;
```

**Security design**: The `table` parameter must be in the allowlist `{"visitors", "click_logs", "messages", "page_views"}` to prevent SQL injection. Limited to 5000 rows to prevent memory overflow.

### 11. Retention Analysis

**Trigger**: `GET /api/admin/retention`

```sql
WITH first_visit AS (
    -- Each visitor's first visit date
    SELECT visitor_id, DATE(MIN(created_at)) as first_day
    FROM page_views WHERE visitor_id IS NOT NULL
    GROUP BY visitor_id
),
daily_activity AS (
    -- Each visitor's daily activity (deduplicated)
    SELECT DISTINCT visitor_id, DATE(created_at) as active_day
    FROM page_views WHERE visitor_id IS NOT NULL
)
SELECT
    fv.first_day::text as cohort_date,
    COUNT(DISTINCT fv.visitor_id) as cohort_size,
    -- Day 0: First day (= cohort_size)
    COUNT(DISTINCT CASE WHEN da.active_day = fv.first_day     THEN da.visitor_id END) as day_0,
    -- Day 1: Next day return
    COUNT(DISTINCT CASE WHEN da.active_day = fv.first_day + 1 THEN da.visitor_id END) as day_1,
    -- Day 7: One week later return
    COUNT(DISTINCT CASE WHEN da.active_day = fv.first_day + 7 THEN da.visitor_id END) as day_7,
    -- Day 30: One month later return
    COUNT(DISTINCT CASE WHEN da.active_day = fv.first_day + 30 THEN da.visitor_id END) as day_30
FROM first_visit fv
LEFT JOIN daily_activity da ON fv.visitor_id = da.visitor_id
WHERE fv.first_day > NOW() - INTERVAL '60 days'
GROUP BY fv.first_day
ORDER BY fv.first_day DESC LIMIT 30;
```

**SQL techniques**:
- **CTE (WITH clause)**: Breaks complex logic into readable named subqueries
- **Retention definition**: Day N = whether there's an active record N days after first visit
- **`fv.first_day + 1`**: PostgreSQL date arithmetic — directly add integer days
- **`COUNT(DISTINCT CASE WHEN ...)`**: Conditional counting — only count unique visitors meeting the condition
- This is the most complex SQL in the entire application and the best candidate for Redis caching (TTL 300s)

---

## Data Seeding

`init_db()` runs automatically on application startup:

```
init_db()
  │
  ├── CREATE TABLE IF NOT EXISTS × 9 tables
  ├── CREATE INDEX IF NOT EXISTS × 6 indexes
  ├── COMMIT
  │
  ├── Is the posts table empty?
  │     └── Yes → _seed_blog_posts(): Insert 5 sample articles + 10 tags
  │
  └── Is the projects table empty?
        └── Yes → _seed_github_projects(): Call GitHub API to sync repos
```

### Blog Seed Data

5 auto-created articles:

| Slug | Tags |
|---|---|
| `azure-openai-service-troubleshooting-guide` | Azure, AI, Troubleshooting |
| `building-ai-support-diagnostic-tools-python` | Python, AI, Azure, DevOps |
| `postgresql-query-optimization-real-cases` | SQL, Azure, Troubleshooting |
| `azure-networking-private-endpoints-explained` | Azure, Networking, Cloud |
| `my-journey-from-ai-support-to-building-tools` | Career, AI, Azure |

### Tag Seed Data

10 preset tags: Azure, AI, Python, Troubleshooting, DevOps, Machine Learning, Cloud, SQL, Networking, Career

### Seed SQL Pattern

```sql
-- Insert post (skip if already exists)
INSERT INTO posts (slug, title, summary, content, status, published_at)
VALUES (%s, %s, %s, %s, 'published', NOW())
ON CONFLICT (slug) DO NOTHING RETURNING id;

-- Insert tag (skip if already exists)
INSERT INTO tags (name) VALUES (%s)
ON CONFLICT (name) DO NOTHING;

-- Insert association (skip if already exists)
INSERT INTO post_tags (post_id, tag_id) VALUES (%s, %s)
ON CONFLICT DO NOTHING;
```

`ON CONFLICT DO NOTHING` ensures repeated startups don't produce duplicate data.

---

## Connection Management Pattern

Currently uses a **short connection pattern** (new connection per request, closed after use):

```python
conn = get_db()
cur = conn.cursor()
cur.execute(...)
conn.commit()
cur.close()
conn.close()
```

**Pros**: Simple, reliable, no connection leak risk  
**Cons**: Each request has TCP + SSL handshake overhead (~10–20ms)

**Future optimization**: If traffic grows, introduce connection pooling:
```python
# Option: psycopg2.pool.ThreadedConnectionPool
from psycopg2.pool import ThreadedConnectionPool
pool = ThreadedConnectionPool(2, 10, DATABASE_URL, sslmode="require")
conn = pool.getconn()
# ... use connection ...
pool.putconn(conn)
```

---

## Azure Portal Monitoring

### Key Metrics

Open Azure Portal → `aimeelan-server` → **Monitoring → Metrics**

| Metric | Description | Normal Range |
|---|---|---|
| **CPU percent** | Database server CPU usage | < 70% |
| **Memory percent** | Memory usage | < 80% |
| **Active Connections** | Current active connection count | 1–10 (gunicorn workers) |
| **Storage percent** | Disk space usage | < 80% |
| **Storage Used** | Used storage (MB) | Current data volume is small, < 100MB |
| **Maximum Used Transaction IDs** | Transaction ID usage | < 50% (needs VACUUM if approaching limit) |
| **Read IOPS / Write IOPS** | Disk read/write operations per second | Write IOPS concentrates during PV recording |
| **Network Bytes In/Out** | Network traffic | Depends on query result size |
| **Succeeded Connections** | Successfully established connections | Should equal request count (short connection pattern) |
| **Failed Connections** | Failed connection attempts | Should remain 0 |
| **Deadlocks** | Deadlock count | Should remain 0 |
| **Database Size** | Database size | Slow growth is normal |

### Setting Up Metrics Charts

Azure Portal → `aimeelan-server` → **Monitoring → Metrics**

**Chart 1: Server Health**
- CPU percent + Memory percent
- Time range: Last 24 hours
- Purpose: Ensure server is not overloaded

**Chart 2: Connection Status**
- Active Connections + Failed Connections
- Time range: Last 6 hours
- Purpose: Monitor connection health

**Chart 3: Storage Growth**
- Storage Used
- Time range: Last 30 days
- Purpose: Estimate storage scaling needs

**Chart 4: IO Activity**
- Read IOPS + Write IOPS
- Time range: Last 1 hour
- Purpose: Identify high-load periods

### Alert Configuration

Azure Portal → `aimeelan-server` → **Monitoring → Alerts → + Create alert rule**

| Alert | Condition | Severity |
|---|---|---|
| High CPU | CPU percent > 80% for 5 minutes | Critical |
| Connection failures | Failed Connections > 5 / 5 minutes | Critical |
| Storage space | Storage percent > 80% | Warning |
| Deadlocks | Deadlocks > 0 | Warning |
| Too many connections | Active Connections > 50 | Warning |

---

## Common Maintenance Commands

### Connecting to the Database

**Method 1: Azure Portal → `aimeelan-server` → Connect**

Use Cloud Shell or Azure Data Studio to connect directly.

**Method 2: Local psql (requires firewall rule allowing your IP)**

```bash
psql "host=aimeelan-server.postgres.database.azure.com dbname=aimeelan-database user=<your-user> sslmode=require"
```

**Method 3: Azure Portal → `aimeelan-database` → Query editor (preview)**

### Data Queries

```sql
-- View all tables
\dt

-- Row count per table
SELECT schemaname, relname, n_live_tup
FROM pg_stat_user_tables ORDER BY n_live_tup DESC;

-- Last 10 visitors
SELECT * FROM visitors ORDER BY created_at DESC LIMIT 10;

-- Last 10 page views
SELECT * FROM page_views ORDER BY created_at DESC LIMIT 10;

-- Visitor and PV count for a specific day
SELECT
    (SELECT COUNT(*) FROM visitors WHERE DATE(created_at) = '2026-03-11') as visitors,
    (SELECT COUNT(*) FROM page_views WHERE DATE(created_at) = '2026-03-11') as pageviews;

-- Page visit ranking
SELECT page, COUNT(*) as views, AVG(duration_sec)::int as avg_sec
FROM page_views GROUP BY page ORDER BY views DESC;

-- Blog post view ranking
SELECT slug, title, views FROM posts ORDER BY views DESC;

-- Email domain distribution
SELECT SPLIT_PART(email, '@', 2) as domain, COUNT(*)
FROM visitors GROUP BY domain ORDER BY count DESC LIMIT 10;
```

### Performance Diagnostics

```sql
-- View table sizes
SELECT relname,
       pg_size_pretty(pg_total_relation_size(relid)) as total_size,
       pg_size_pretty(pg_relation_size(relid)) as table_size,
       pg_size_pretty(pg_indexes_size(relid)) as index_size
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC;

-- View index usage
SELECT indexrelname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes ORDER BY idx_scan DESC;

-- View dead tuples (tables needing VACUUM)
SELECT relname, n_live_tup, n_dead_tup,
       ROUND(100.0 * n_dead_tup / GREATEST(n_live_tup + n_dead_tup, 1), 1) as dead_pct,
       last_vacuum, last_autovacuum
FROM pg_stat_user_tables WHERE n_dead_tup > 100 ORDER BY dead_pct DESC;

-- View slowest queries (requires pg_stat_statements extension)
SELECT query, calls, mean_exec_time::numeric(10,2) as avg_ms,
       total_exec_time::numeric(10,2) as total_ms
FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;

-- View current active connections
SELECT pid, usename, application_name, client_addr, state, query
FROM pg_stat_activity WHERE datname = 'aimeelan-database';
```

### Data Cleanup

```sql
-- Delete page views older than 90 days (free up space)
DELETE FROM page_views WHERE created_at < NOW() - INTERVAL '90 days';

-- Delete click logs older than 90 days
DELETE FROM click_logs WHERE clicked_at < NOW() - INTERVAL '90 days';

-- Run VACUUM after cleanup
VACUUM ANALYZE page_views;
VACUUM ANALYZE click_logs;

-- Reclaim space after large deletes (note: locks the table)
VACUUM FULL page_views;
```

---

## Performance Optimization Notes

### Currently Implemented Optimizations

| Optimization | Effect |
|---|---|
| 6 B-tree indexes | Speed up WHERE/JOIN/ORDER BY |
| Redis cache layer | Reduce repeated queries (see REDIS.md) |
| `LIMIT + OFFSET` pagination | Avoid full table scans |
| `ON CONFLICT DO NOTHING/UPDATE` | Atomic upsert — no need for SELECT then decide |
| `RETURNING id` | Get ID immediately after insert — saves one SELECT |
| `::text` type cast | Convert at database layer — reduces Python-side processing |

### Possible Future Optimizations (When Traffic Grows)

| Direction | Approach |
|---|---|
| Connection pooling | Introduce `psycopg2.pool.ThreadedConnectionPool` |
| Cursor pagination | Use keyset pagination instead of OFFSET for large tables |
| Table partitioning | Partition `page_views` by month for faster time-range queries |
| Read replica | Route admin dashboard queries to a Read Replica |
| Batch writes | Buffer PVs in a Redis queue, batch INSERT |
| `pg_stat_statements` | Enable to analyze slow queries |

---

## FAQ

**Q: Does the database create tables automatically?**  
A: Yes. `init_db()` runs `CREATE TABLE IF NOT EXISTS` on application startup — no manual table creation needed.

**Q: Will repeated startups produce duplicate data?**  
A: No. All CREATE TABLE statements use `IF NOT EXISTS`, and seed data uses `ON CONFLICT DO NOTHING`.

**Q: Will the page_views table grow indefinitely?**  
A: Yes. Periodic cleanup of data older than 90 days is recommended (see "Data Cleanup" section), or export to CSV via the admin panel before deleting.

**Q: Why use short connections instead of connection pooling?**  
A: Current traffic is low; short connections are sufficient and the code is simpler. Connection pooling provides noticeable benefits only when concurrency exceeds ~50.

**Q: How do I back up the database?**  
A: Azure PostgreSQL Flexible Server automatically backs up daily, retaining 7–35 days (configurable in Azure Portal). Manual backup: Azure Portal → `aimeelan-server` → Backup and restore.

**Q: Can I connect to the Azure database from my local machine?**  
A: Yes. You need to add your IP to the firewall allowlist in Azure Portal → `aimeelan-server` → Networking.

**Q: Where are passwords stored?**  
A: Connection strings are stored in Azure App Service environment variables, not in the code. Local development uses default localhost configuration.
