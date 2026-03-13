# Backup & Migration Guide — What To Do When You Lose Azure Access

When your company Azure account is revoked (e.g., leaving the job), you'll lose access to:
- Azure App Service (website hosting)
- Azure PostgreSQL Flexible Server (all your data)
- Azure Cache for Redis (cache layer)

This guide covers **what exactly you lose, what needs saving, and how to migrate everything to a personal account**.

---

## Table of Contents

- [What Will You Lose?](#what-will-you-lose)
- [What Does NOT Need Backup](#what-does-not-need-backup)
  - [Why Redis Doesn't Need Backup](#why-redis-doesnt-need-backup)
  - [Why App Service Doesn't Need Backup](#why-app-service-doesnt-need-backup)
- [What MUST Be Backed Up](#what-must-be-backed-up)
  - [1. PostgreSQL Data (CRITICAL)](#1-postgresql-data-critical)
  - [2. Environment Variables (IMPORTANT)](#2-environment-variables-important)
  - [3. Code Repository](#3-code-repository)
  - [4. Gmail App Password](#4-gmail-app-password)
- [Migration Plan: Move to a New Platform](#migration-plan-move-to-a-new-platform)
  - [Why Railway Is Recommended](#why-railway-is-recommended)
  - [Step-by-Step Migration to Railway](#step-by-step-migration-to-railway)
  - [Code Compatibility — Zero Changes Needed](#code-compatibility--zero-changes-needed)
- [Architecture: Before vs After](#architecture-before-vs-after)
- [Fault Tolerance: What If You Skip Redis?](#fault-tolerance-what-if-you-skip-redis)
- [Pre-Departure Checklist](#pre-departure-checklist)

---

## What Will You Lose?

| Component | Azure Resource | What's Inside | Lost? | Impact |
|-----------|---------------|---------------|-------|--------|
| **Web Hosting** | App Service `aimeelan` | Running Flask server | Yes | Website goes offline |
| **Database** | PostgreSQL `aimeelan-server` | 9 tables: visitors, posts, tags, projects, messages, click_logs, page_views, visitor_sessions, post_tags | Yes | **All data permanently lost** |
| **Cache** | Redis `aimee-cache` | Cached API responses (posts, tags, stats, etc.) | Yes | No real impact (auto-rebuilds) |
| **CI/CD** | GitHub Actions workflow | Pipeline config pointing to Azure | Partially | Workflow file stays in repo, but Azure credentials expire |
| **Networking** | VNet, Private Endpoints | Secure connection between services | Yes | Not needed on new platform |

---

## What Does NOT Need Backup

### Why Redis Doesn't Need Backup

Redis in this project is a **pure read-through cache**. It contains zero original data — everything is a copy from PostgreSQL.

How it works:

```
Request comes in
    │
    ├── cache_get(key) → Redis has it? → Return cached data (fast)
    │
    └── cache_get(key) → Redis empty?
            │
            ├── Query PostgreSQL → Get original data
            ├── cache_set(key, data, ttl) → Store in Redis for next time
            └── Return data
```

When Redis is completely gone:
- Every `cache_get()` returns `None`
- Every request goes straight to PostgreSQL
- First visitor to each page triggers a fresh DB query
- Data is 100% intact — just served ~50ms slower instead of ~1ms

The code is designed for this:

```python
redis_client = None  # If Redis URL is missing, this stays None

def cache_get(key):
    if redis_client:          # Redis doesn't exist? Skip entirely
        try:
            val = redis_client.get(key)
            return json.loads(val) if val else None
        except Exception:     # Redis errored? Return None, treat as miss
            return None
    return None               # No Redis → always miss → always query DB
```

**Degradation behavior when Redis is unavailable:**

| Function | Normal (Redis OK) | Degraded (No Redis) |
|----------|-------------------|---------------------|
| `cache_get()` | Returns cached data | Returns `None` → queries DB |
| `cache_set()` | Writes to cache | Silently skipped |
| `cache_delete()` | Clears specific caches | Silently skipped |
| Website functionality | Fast (cached) | Works fine, slightly slower |
| Data integrity | 100% | 100% |

### Why App Service Doesn't Need Backup

App Service is just a computer running your code. The code itself lives in GitHub. You can deploy the same code to any platform that runs Python.

---

## What MUST Be Backed Up

### 1. PostgreSQL Data (CRITICAL)

This is the **only irreplaceable thing**. Your database contains real user data, blog posts, and analytics that cannot be recreated.

**All 9 tables at risk:**

| Table | Records | Why It Matters |
|-------|---------|---------------|
| `visitors` | All verified visitors | Names, emails, verification tokens |
| `posts` | 5 blog posts | Full Markdown content, titles, slugs |
| `tags` | 10 tags | Azure, AI, Python, etc. |
| `post_tags` | Post-tag relationships | Which tags belong to which posts |
| `projects` | GitHub repos | Synced project data |
| `messages` | Contact form submissions | Visitor messages to you |
| `click_logs` | Click tracking events | Which elements were clicked |
| `page_views` | Page view analytics | Pages, referrers, durations, screen widths |
| `visitor_sessions` | Session tracking | Session start/end, page counts |

**Method 1: pg_dump (RECOMMENDED — full backup)**

```powershell
pg_dump "host=aimeelan-server.postgres.database.azure.com dbname=aimeelan-database user=prjxaadsjr password=YOUR_PASSWORD sslmode=require" > C:\Users\jingwang1\backup.sql
```

This single file contains:
- All 9 table schemas (CREATE TABLE statements)
- All 6 indexes
- All data rows (INSERT statements)
- Everything needed to rebuild the exact database on any PostgreSQL server

To restore on a new server:
```bash
psql "postgresql://user:pass@new-host:5432/dbname" < backup.sql
```

**Method 2: CSV export via admin API (partial — only 4 tables)**

```
https://aimeelan.azurewebsites.net/api/admin/export/visitors
https://aimeelan.azurewebsites.net/api/admin/export/click_logs
https://aimeelan.azurewebsites.net/api/admin/export/messages
https://aimeelan.azurewebsites.net/api/admin/export/page_views
```

**Warning:** CSV export only covers 4 of 9 tables. It does NOT include blog posts, tags, projects, post_tags, or visitor_sessions. Use `pg_dump` instead.

**Where to save:** Personal email, personal cloud drive (Google Drive, OneDrive personal), or USB drive — anywhere your company cannot revoke access.

### 2. Environment Variables (IMPORTANT)

These are the secrets and configuration values your app needs to run:

```powershell
# View all current settings
az webapp config appsettings list --name aimeelan --resource-group aimee-test-env --output table

# Also check connection strings
az webapp config connection-string list --name aimeelan --resource-group aimee-test-env --output table
```

Save everything to a file on your personal device:

```env
# === Flask Core ===
SECRET_KEY=your-actual-secret-key-value

# === Admin Authentication ===
ADMIN_USER=admin
ADMIN_PASS_HASH=your-actual-bcrypt-hash
# (or ADMIN_PASS=your-plain-password if you use that instead)

# === Email Notifications ===
OWNER_EMAIL=your-email@example.com
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-gmail@gmail.com
SMTP_PASS=your-16-character-app-password

# === GitHub Integration ===
GITHUB_USERNAME=hahAI111
GITHUB_TOKEN=your-github-personal-access-token

# === Database (will change on new platform) ===
AZURE_POSTGRESQL_CONNECTIONSTRING=host=aimeelan-server.postgres.database.azure.com dbname=aimeelan-database user=prjxaadsjr password=xxx
AZURE_REDIS_CONNECTIONSTRING=aimee-cache.redis.cache.windows.net:6380,password=xxx,ssl=True,abortConnect=False
```

### 3. Code Repository

Your code is on GitHub (`hahAI111/aimeewebpage`). **Confirm your GitHub account is personal:**

1. Go to [github.com/settings/emails](https://github.com/settings/emails)
2. If your primary email is a company email → Add a personal email and set it as primary
3. Ensure 2FA is tied to your personal phone, not a company device

As a safety measure, also clone to your personal computer:
```bash
git clone https://github.com/hahAI111/aimeewebpage.git
```

### 4. Gmail App Password

Your Gmail App Password (`SMTP_PASS`) is stored in Azure environment variables. Once Azure access is gone, you can't retrieve it. **Write it down now.**

If you lose it, you can always generate a new one at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) — but only if you still have access to that Gmail account with 2FA enabled.

---

## Migration Plan: Move to a New Platform

### Why Railway Is Recommended

| Feature | Azure (Company) | Railway (Personal) | Render | Personal Azure |
|---------|-----------------|-------------------|--------|---------------|
| Flask hosting | App Service ~$13/mo | **Free ($5 credit/mo)** | Free (750 hrs/mo) | Free 12 months |
| PostgreSQL | Flexible Server ~$15/mo | **Free (1GB)** | Free (1GB, 90 days) | ~$15/mo |
| Redis | Cache ~$16/mo | **Free (25MB)** | Free (25MB) | ~$16/mo |
| **Total monthly cost** | **~$44/mo** | **$0** | **$0** | $0 → ~$44/mo |
| Auto-deploy from GitHub | Yes (GitHub Actions) | Yes (built-in) | Yes (built-in) | Yes (GitHub Actions) |
| Custom domain | Yes | Yes | Yes | Yes |
| SSL/HTTPS | Auto | Auto | Auto | Auto |

Railway is the closest experience to Azure — free, auto-deploys from GitHub, includes PostgreSQL + Redis.

### Step-by-Step Migration to Railway

**Step 1: Sign up**
- Go to [railway.app](https://railway.app)
- Sign in with your GitHub account

**Step 2: Create project from GitHub**
- Click **New Project → Deploy from GitHub Repo**
- Select `hahAI111/aimeewebpage`
- Railway auto-detects Python, runs `pip install -r requirements.txt`

**Step 3: Add PostgreSQL**
- In the project, click **+ New → Database → PostgreSQL**
- Railway creates a PostgreSQL instance and provides connection variables automatically

**Step 4: Add Redis**
- Click **+ New → Database → Redis**
- Railway creates a Redis instance with connection variables

**Step 5: Import your data**

Get your Railway PostgreSQL URL from the Variables tab, then:
```bash
psql "postgresql://user:pass@host:port/railway" < backup.sql
```

All 9 tables, all data, all indexes — restored.

**Step 6: Set environment variables**

In Railway project → your web service → **Variables** tab:

```
SECRET_KEY=your-saved-value
ADMIN_USER=admin
ADMIN_PASS_HASH=your-saved-bcrypt-hash
OWNER_EMAIL=your@email.com
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-gmail@gmail.com
SMTP_PASS=your-saved-app-password
GITHUB_USERNAME=hahAI111
GITHUB_TOKEN=your-github-token
```

For database connections, link to Railway's auto-generated variables:
- `AZURE_POSTGRESQL_CONNECTIONSTRING` → `${{Postgres.DATABASE_URL}}`
- `AZURE_REDIS_CONNECTIONSTRING` → `${{Redis.REDIS_URL}}`

**Step 7: Set start command**

Go to **Settings → Start Command**:
```bash
gunicorn --bind=0.0.0.0:$PORT --timeout 600 app:app
```

**Step 8: Done!**

Railway gives you a URL like `aimeewebpage-production.up.railway.app`. Every future `git push` auto-redeploys.

### Code Compatibility — Zero Changes Needed

Your connection string parsers already handle multiple formats:

```python
def _parse_pg_conn(raw):
    if not raw or raw.startswith("host="):
        return raw                     # libpq format → pass through
    # converts ADO.NET format...       # Azure ADO.NET → converted

def _parse_redis_conn(raw):
    if not raw or raw.startswith("redis"):
        return raw                     # redis:// URL → pass through
    # converts Azure format...         # Azure comma-separated → converted
```

- Railway provides PostgreSQL as `postgresql://user:pass@host:port/db` → `_parse_pg_conn` passes it through (starts with neither `host=` nor ADO.NET)
- Railway provides Redis as `redis://...` → `_parse_redis_conn` passes it through (starts with `redis`)

One small tweak may be needed — add `postgresql://` handling to the PostgreSQL parser:

```python
def _parse_pg_conn(raw):
    if not raw or raw.startswith("host=") or raw.startswith("postgres"):
        return raw  # handles: host=..., postgresql://..., postgres://...
    # ... existing ADO.NET conversion
```

This is a one-line change. Everything else works as-is.

---

## Architecture: Before vs After

```
====== NOW: Azure (Company Account) ======

Internet
    │
    ▼
Azure App Service (aimeelan)          ← Runs gunicorn + Flask
    │                                    Code: from GitHub via GitHub Actions
    ├── VNet Integration ──┐
    │                      ▼
    ├── Azure PostgreSQL (aimeelan-server)     ← 9 tables, all data
    │   (Private Endpoint, SSL, port 5432)
    │
    └── Azure Redis (aimee-cache)              ← Cache only
        (Private Endpoint, SSL, port 6380)



====== AFTER: Railway (Personal Account) ======

Internet
    │
    ▼
Railway Web Service                   ← Runs gunicorn + Flask
    │                                    Code: from GitHub (auto-deploy)
    │
    ├── Railway PostgreSQL            ← 9 tables, data restored from backup.sql
    │   (Internal network, SSL)
    │
    └── Railway Redis                 ← Cache, auto-rebuilds from DB
        (Internal network)

Same code. Same features. Same behavior. Different infrastructure provider.
```

---

## Fault Tolerance: What If You Skip Redis?

You can choose NOT to set up Redis on the new platform. The website still works perfectly:

| Feature | With Redis | Without Redis |
|---------|-----------|--------------|
| Blog list | Cached 120s, then refreshes | Every request queries PostgreSQL |
| Single post | Cached 300s | Every request queries PostgreSQL |
| Admin dashboard | Cached 60s (8 SQL queries) | 8 SQL queries every time |
| Tag list | Cached 300s | Every request queries PostgreSQL |
| Projects list | Cached 300s | Every request queries PostgreSQL |
| Response time | ~1ms (cache hit) | ~50-100ms (database query) |
| Data correctness | 100% | 100% |
| Website functionality | Full | Full |

For a personal portfolio with modest traffic, skipping Redis is totally fine. Add it later if performance matters.

---

## Pre-Departure Checklist

Complete these steps **BEFORE** your last day:

| # | Action | Priority | Status |
|---|--------|----------|--------|
| 1 | Confirm GitHub account is personal (not company email) | Critical | ⬜ |
| 2 | `pg_dump` full database backup → save to personal device | Critical | ⬜ |
| 3 | Export all environment variables → save to personal device | Critical | ⬜ |
| 4 | Save Gmail App Password separately | Important | ⬜ |
| 5 | `git clone` to personal computer | Important | ⬜ |
| 6 | Save GitHub Personal Access Token | Important | ⬜ |
| 7 | Register Railway / Render personal account | Medium | ⬜ |
| 8 | Deploy to new platform | Medium | ⬜ |
| 9 | `psql < backup.sql` import data to new database | Medium | ⬜ |
| 10 | Set all environment variables on new platform | Medium | ⬜ |
| 11 | Test every page and feature on new platform | Medium | ⬜ |
| 12 | Delete or update Azure GitHub Actions workflow | Low | ⬜ |

**Items 1-6 are time-sensitive** — do them while you still have access to the company computer and Azure account. Items 7-12 can be done anytime from a personal computer.
