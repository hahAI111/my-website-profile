# Redis Cache — Usage & Monitoring Guide

This project uses **Azure Cache for Redis** (instance: `aimee-cache`, Basic SKU) as a cache layer
to reduce PostgreSQL query load and accelerate API responses.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Connection Configuration](#connection-configuration)
- [Core Functions](#core-functions)
- [Cache Keys Overview](#cache-keys-overview)
- [Cache Flow by API](#cache-flow-by-api)
  - [Blog Post List](#1-blog-post-list)
  - [Single Post Detail](#2-single-post-detail)
  - [Tag List](#3-tag-list)
  - [GitHub Project List](#4-github-project-list)
  - [Admin Stats Dashboard](#5-admin-stats-dashboard)
  - [Retention Analysis](#6-retention-analysis)
- [Admin Dashboard Redis Panel](#admin-dashboard-redis-panel)
- [Cache Invalidation Strategy](#cache-invalidation-strategy)
- [Fault Tolerance Design](#fault-tolerance-design)
- [Azure Portal Monitoring](#azure-portal-monitoring)
  - [Key Metrics](#key-metrics)
  - [Setting Up Metrics Charts](#setting-up-metrics-charts)
  - [Alert Configuration](#alert-configuration)
- [Console Command Testing](#console-command-testing)
  - [Common Commands](#common-commands)
  - [Full Test Walkthrough](#full-test-walkthrough)
- [Performance Comparison](#performance-comparison)
- [FAQ](#faq)

---

## Architecture Overview

```
User Request → Flask API
              │
              ├── cache_get(key) ──→ Redis (hit?)
              │        ├── Hit ──→ Return JSON directly (~1ms)
              │        └── Miss ──┐
              │                   ▼
              ├── Query PostgreSQL (~50-100ms)
              │
              └── cache_set(key, result, ttl) ──→ Write to Redis
                                                  (auto-expires after TTL seconds)
```

Redis acts as a **Read-Through Cache** in this project:
1. Check Redis first — if hit, skip the database
2. On miss, query PostgreSQL and write the result to Redis
3. On data updates, actively clear related caches

---

## Connection Configuration

### Environment Variables

Azure App Service automatically injects the Redis connection string. The code reads by priority:

```
AZURE_REDIS_CONNECTIONSTRING          ← Primary
REDISCACHECONNSTR_azure_redis_cache   ← Fallback (Azure auto-bound prefix format)
```

### Connection String Parsing

Azure provides the connection string in ADO.NET format:
```
aimee-cache.redis.cache.windows.net:6380,password=xxxxx,ssl=True,abortConnect=False
```

The `_parse_redis_conn()` function converts it to the URI format required by Python's `redis` library:
```
rediss://:xxxxx@aimee-cache.redis.cache.windows.net:6380/0
```

- `rediss://` = TLS/SSL connection (note the extra `s`)
- Port `6380` = Azure Redis SSL port
- `/0` = Uses Redis database 0

### Connection Initialization

```python
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
redis_client.ping()  # Verify connection
```

`decode_responses=True` automatically decodes bytes to strings, eliminating manual `.decode()` calls.

---

## Core Functions

Three cache utility functions are defined in `app.py`:

### `cache_get(key)`

```python
def cache_get(key):
    if redis_client:
        val = redis_client.get(key)           # Redis GET command
        return json.loads(val) if val else None  # JSON deserialization
    return None
```

- Underlying command: `GET <key>`
- Returns: Python dict/list (on hit) or `None` (on miss / Redis unavailable)
- Time complexity: O(1)

### `cache_set(key, value, ttl=300)`

```python
def cache_set(key, value, ttl=300):
    if redis_client:
        redis_client.setex(key, ttl, json.dumps(value))  # SET + EXPIRE atomic operation
```

- Underlying command: `SETEX <key> <ttl> <json_string>`
- `ttl`: Expiration time in seconds; Redis auto-deletes the key after expiry
- Data format: Stored as JSON-serialized string
- Time complexity: O(1)

### `cache_delete(pattern)`

```python
def cache_delete(pattern):
    if redis_client:
        for key in redis_client.scan_iter(match=pattern):
            redis_client.delete(key)
```

- Underlying commands: `SCAN 0 MATCH <pattern>` + `DEL <key>`
- Purpose: Batch-delete caches by wildcard pattern (e.g. `stats:*` deletes all stats caches)
- `SCAN` uses cursor-based iteration and won't block Redis like `KEYS *`
- Time complexity: O(N), where N = number of matching keys

---

## Cache Keys Overview

| Key Format | Example | TTL | Source API |
|---|---|---|---|
| `posts:list:{tag}:{page}:{per_page}` | `posts:list::1:10` | 120s | `GET /api/posts` |
| `post:{slug}` | `post:azure-openai-service-troubleshooting-guide` | 300s | `GET /api/posts/<slug>` |
| `tags:all` | `tags:all` | 300s | `GET /api/tags` |
| `projects:all` | `projects:all` | 300s | `GET /api/projects` |
| `stats:overview` | `stats:overview` | 60s | `GET /api/admin/stats` |
| `stats:retention` | `stats:retention` | 300s | `GET /api/admin/retention` |

**TTL Design Principles**:
- 60 seconds: Data requiring near real-time freshness (admin stats dashboard)
- 120 seconds: Frequently changing list data (paginated post list)
- 300 seconds: Relatively stable data (single post, tags, projects, retention analysis)

---

## Cache Flow by API

### 1. Blog Post List

**Route**: `GET /api/posts?tag=Azure&page=1&per_page=10`  
**Cache key**: `posts:list:Azure:1:10`  
**TTL**: 120 seconds

```
Request → cache_get("posts:list:Azure:1:10")
         │
         ├── Hit → Return JSON directly
         │
         └── Miss
              ├── PostgreSQL: SELECT posts + JOIN tags (paginated query)
              ├── PostgreSQL: SELECT COUNT(*) (total)
              ├── Assemble {posts, total, page, per_page}
              ├── cache_set(key, result, ttl=120) → Store in Redis
              └── Return JSON
```

**Note**: Different tag/page/per_page combinations generate different cache keys and don't interfere with each other.

### 2. Single Post Detail

**Route**: `GET /api/posts/azure-openai-service-troubleshooting-guide`  
**Cache key**: `post:azure-openai-service-troubleshooting-guide`  
**TTL**: 300 seconds

```
Request → cache_get("post:azure-openai-...")
         │
         ├── Hit
         │     ├── UPDATE posts SET views = views + 1  ← Still updates view count
         │     └── Return cached JSON
         │
         └── Miss
              ├── PostgreSQL: SELECT post + JOIN tags
              ├── UPDATE posts SET views = views + 1
              ├── cache_set(key, post, ttl=300)
              └── Return JSON
```

**Key design**: Even on cache hit, the view count UPDATE still runs against PostgreSQL.
This ensures:
- **Post content** is read from cache (fast)
- **View count** is always accurately written to the database

### 3. Tag List

**Route**: `GET /api/tags`  
**Cache key**: `tags:all`  
**TTL**: 300 seconds

```
Request → cache_get("tags:all")
         ├── Hit → Return [{name, post_count}, ...]
         └── Miss → PostgreSQL: SELECT tags JOIN post_tags
                  → cache_set → Return
```

**Note**: Tag count rarely changes; 300-second caching significantly reduces this aggregation query's overhead.

### 4. GitHub Project List

**Route**: `GET /api/projects`  
**Cache key**: `projects:all`  
**TTL**: 300 seconds

```
Read: cache_get("projects:all") → Hit/Miss same as above
Sync: POST /api/projects/sync → After completion: cache_delete("projects:*")
```

**Note**: After project sync, the cache is actively cleared so the next request loads fresh data from the database.

### 5. Admin Stats Dashboard

**Route**: `GET /api/admin/stats`  
**Cache key**: `stats:overview`  
**TTL**: 60 seconds

This is the most complex query, containing 8 SQL statements:
- Total visitors, clicks, messages, PVs, and post count
- Last 30 days daily visitor trend
- Last 30 days daily PV trend
- Top 15 clicked elements
- Top 10 pages with average duration
- Top 15 email domain distribution
- Device type distribution
- Recent messages Top 10
- Top posts Top 10

**Why 60-second TTL**: Admin needs near real-time data, but these queries are expensive.
60-second caching balances "freshness" and "performance."

**Additional mechanism**: When a visitor submits a message (`POST /api/contact`), `cache_delete("stats:*")` runs to ensure the admin sees new messages immediately.

### 6. Retention Analysis

**Route**: `GET /api/admin/retention`  
**Cache key**: `stats:retention`  
**TTL**: 300 seconds

```
Request → cache_get("stats:retention")
         ├── Hit → Return retention table
         └── Miss → PostgreSQL: CTE query (first_visit + daily_activity)
                  → cache_set → Return
```

**Note**: Retention analysis is the most expensive query (multi-table CTE + heavy DISTINCT calculations); 300-second caching is essential here.

---

## Admin Dashboard Redis Panel

The admin dashboard at `/admin` includes a **dedicated Redis monitoring section** that provides real-time cache visibility without needing to open Azure Portal.

### What It Shows

The `/api/admin/stats` endpoint calls `redis_client.info(section="memory")` and `redis_client.info(section="keyspace")` to gather server-level metrics:

| Metric | Source | Description |
|--------|--------|-------------|
| Connection Status | `redis_client.ping()` | Connected (green) / Offline (gray) |
| Memory Used | `info["used_memory_human"]` | Current memory consumption |
| Peak Memory | `info["used_memory_peak_human"]` | Highest memory usage since last restart |
| Total Keys | `keyspace.db0.keys` | Number of cached keys across all databases |

### Cached Endpoints Table

The panel also displays a table listing all 6 cached API patterns:

| Key Pattern | TTL | What It Caches |
|---|---|---|
| `stats:overview` | 60s | Admin dashboard KPIs & charts |
| `stats:retention` | 300s | Retention cohort analysis |
| `posts:list:*` | 120s | Blog listing with tag/page |
| `post:<slug>` | 300s | Single blog post content |
| `tags:all` | 300s | Tag list with counts |
| `projects:all` | 300s | GitHub projects list |

### UI Components

1. **KPI Card** — 6th card in the KPI grid with a database SVG icon, shows "Connected" (green) or "Offline" (gray)
2. **Redis Cache Status Panel** — 4 mini-KPI cards (Status, Memory, Peak Memory, Keys) + cached endpoints table
3. **Fault Tolerance** — If Redis is unavailable, the panel renders gracefully with "Offline" / "N/A" values instead of crashing

---

## Cache Invalidation Strategy

| Trigger Event | Caches Cleared | Method |
|---|---|---|
| New message submitted (`POST /api/contact`) | `stats:*` | `cache_delete("stats:*")` |
| GitHub project sync (`POST /api/projects/sync`) | `projects:*` | `cache_delete("projects:*")` |
| Any cache reaches TTL | That key itself | Redis auto-expiry |

> This project **does not** have an endpoint to manually clear blog caches — blog post content expires naturally via TTL.
> If you need to immediately update a specific post's cache, you can manually run `DEL post:<slug>` in the Azure Redis console.

---

## Fault Tolerance Design

Redis is an **optional component** in this project — Redis failures will not crash the website:

```python
# On startup: connection failure → redis_client set to None
redis_client = None
if REDIS_URL:
    try:
        redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
    except Exception:
        redis_client = None   # Degrade: all requests go directly to PostgreSQL

# At runtime: every operation has try/except
def cache_get(key):
    if redis_client:        # Redis unavailable? Skip
        try:
            val = redis_client.get(key)
            return json.loads(val) if val else None
        except Exception:   # Read failure? Return None, treat as miss
            return None
    return None
```

**Degradation behavior**:
| Scenario | Redis OK | Redis Unavailable |
|---|---|---|
| `cache_get()` | Returns cached data | Returns `None` (→ query database) |
| `cache_set()` | Writes to cache | Silently skipped |
| `cache_delete()` | Deletes cache | Silently skipped |
| Website functionality | Normal + accelerated | Normal but slightly slower |

---

## Azure Portal Monitoring

### Key Metrics

Open Azure Portal → `aimee-cache` → **Monitoring → Metrics**

| Metric | Description | Normal Range |
|---|---|---|
| **Cache Hits** | Number of `GET` commands that hit the cache | Should be much greater than Misses |
| **Cache Misses** | `GET` commands that missed (key doesn't exist or expired) | Expected after first access / expiry |
| **Cache Hit Rate** | Hits / (Hits + Misses) × 100% | Target > 80% |
| **Connected Clients** | Currently connected client count | Usually 1–5 (gunicorn workers) |
| **Used Memory / Used Memory RSS** | Cache memory in use | Small data volume, usually < 1MB |
| **Total Keys** | Currently stored key count | Depends on page variety, ~5–20 |
| **Evicted Keys** | Keys evicted due to memory pressure | Should be 0 (Basic 250MB is sufficient) |
| **Expired Keys** | Keys auto-deleted by TTL | Normal; higher numbers mean active cache turnover |
| **Get Commands** | Total GET command count | Corresponds to `cache_get()` calls |
| **Set Commands** | Total SET command count | Corresponds to `cache_set()` calls |
| **Total Commands Processed** | All commands total | GET + SET + DEL + PING + ... |
| **Server Load** | Redis server CPU usage | Should be < 70%; Basic SKU is single-core |
| **Cache Latency** | Average command latency | Target < 1ms |

### Setting Up Metrics Charts

1. Azure Portal → `aimee-cache` → Left menu **Monitoring → Metrics**
2. Click **+ Add metric**
3. Recommended charts:

**Chart 1: Cache Hit Rate**
- Metric: `Cache Hits` (Aggregation: Sum)
- Click "Add metric", add `Cache Misses` (Aggregation: Sum)
- Time range: Last 1 hour
- Purpose: Verify cache is working

**Chart 2: Command Volume**
- Metrics: `Get Commands` + `Set Commands`
- Time range: Last 24 hours
- Purpose: Understand cache read/write frequency

**Chart 3: Health Status**
- Metrics: `Connected Clients` + `Server Load`
- Time range: Last 24 hours
- Purpose: Ensure Redis is running normally

**Chart 4: Memory Usage**
- Metric: `Used Memory`
- Time range: Last 7 days
- Purpose: Monitor memory growth trends

### Alert Configuration

Azure Portal → `aimee-cache` → **Monitoring → Alerts → + Create alert rule**

| Alert | Condition | Severity |
|---|---|---|
| Redis overloaded | Server Load > 80% for 5 minutes | Critical |
| Connection lost | Connected Clients = 0 for 5 minutes | Critical |
| Memory near capacity | Used Memory > 200MB | Warning (Basic SKU max is 250MB) |
| Keys being evicted | Evicted Keys > 0 | Warning (indicates insufficient memory) |

---

## Console Command Testing

### Opening the Console

Azure Portal → `aimee-cache` → Left menu **Console**

### Common Commands

```redis
# ────── Check status ──────

DBSIZE                          # Total key count
KEYS *                          # List all keys (use with caution in production)
INFO stats                      # View hit/miss statistics
INFO memory                     # Memory usage

# ────── View specific caches ──────

GET posts:list::1:10            # Blog list (default first page)
GET post:azure-openai-service-troubleshooting-guide   # Specific post
GET tags:all                    # All tags
GET projects:all                # GitHub project list
GET stats:overview              # Admin stats
GET stats:retention             # Retention analysis

# ────── Check expiration time ──────

TTL posts:list::1:10            # Remaining seconds (-2 = expired/doesn't exist)
TTL stats:overview              # Stats cache remaining time

# ────── Manual management ──────

DEL post:azure-openai-service-troubleshooting-guide  # Delete specific post cache
DEL stats:overview              # Delete stats cache, recalculates on next request

# ────── Monitor real-time commands ──────

MONITOR                         # Real-time display of all Redis commands (debug only, Ctrl+C to stop)
```

### Full Test Walkthrough

Follow these steps to verify Redis caching is working correctly:

**Step 1: Check initial state**
```redis
DBSIZE
# Result: (integer) 0   ← If just restarted, or all keys have expired
```

**Step 2: Trigger a cache write**

Visit `https://aimeelan.azurewebsites.net/api/posts` in your browser.

**Step 3: Verify cache was written**
```redis
DBSIZE
# Result: (integer) 1   ← Increased

KEYS *
# Result: 1) "posts:list::1:10"

GET posts:list::1:10
# Result: {"posts": [...], "total": 5, "page": 1, "per_page": 10}

TTL posts:list::1:10
# Result: (integer) 118   ← 118 seconds until expiry
```

**Step 4: Verify cache hit**

Visit `https://aimeelan.azurewebsites.net/api/posts` again (same parameters).

```redis
INFO stats
# Look for these lines:
# keyspace_hits:2      ← GET hit count (second visit hit the cache)
# keyspace_misses:1    ← GET miss count (first visit was a miss)
```

**Step 5: Wait for expiration**

Wait 120 seconds:
```redis
GET posts:list::1:10
# Result: (nil)   ← Auto-expired

TTL posts:list::1:10
# Result: (integer) -2   ← Key doesn't exist
```

**Step 6: Test active invalidation**

```redis
# First trigger some caches
# Visit /api/posts, /api/tags, /api/admin/stats in browser

KEYS *
# Result: 1) "posts:list::1:10"
#         2) "tags:all"
#         3) "stats:overview"

# Simulate cache_delete("stats:*")
SCAN 0 MATCH stats:*
# Shows matching keys
DEL stats:overview
# Result: (integer) 1

KEYS *
# stats:overview has been deleted
```

**Step 7: Real-time monitoring (MONITOR)**

```redis
MONITOR
```

Then visit your website in another browser tab. The console will show in real time:
```
1710000000.123456 [0 172.x.x.x:xxxxx] "GET" "posts:list::1:10"
1710000000.234567 [0 172.x.x.x:xxxxx] "SETEX" "posts:list::1:10" "120" "{\"posts\":...}"
```

Press Ctrl+C to stop MONITOR.

---

## Performance Comparison

| Scenario | Without Redis (direct DB) | With Redis |
|---|---|---|
| Blog list request | 2 SQL queries each time (query + count) | First time queries DB; next 120s: 0 SQL |
| Single post request | 3 SQL queries each time | First time 3 queries; subsequent: only 1 `UPDATE views` |
| Admin stats dashboard | 8 complex SQL queries each time | First time 8 queries; next 60s: 0 SQL |
| Retention analysis | 1 heavy CTE query each time | First time 1 query; next 300s: 0 SQL |
| 10 concurrent blog visitors | 10 × 2 = 20 SQL queries | 1 × 2 + 0 = 2 SQL queries |
| Response latency | ~50–100ms | First time ~50ms; subsequent ~1ms |

---

## FAQ

**Q: Will the website crash if Redis goes down?**  
A: No. All cache operations are wrapped in try/except. When Redis is unavailable, the system automatically degrades to querying PostgreSQL directly each time.

**Q: I edited a blog post — how does the cache update?**  
A: Currently there is no "edit post" API, so this situation doesn't arise. If an edit feature is added in the future, the save endpoint should call `cache_delete("post:*")` and `cache_delete("posts:list:*")`. In an emergency, you can run `DEL post:<slug>` in the Azure Redis console.

**Q: Is the Basic SKU sufficient?**  
A: For the current volume (5 posts, a few projects), Basic SKU (250MB, single core) is more than enough. All cached data combined is under 1MB. Consider upgrading to Standard when daily PVs exceed 10,000.

**Q: Is the cached data secure?**  
A: Azure Redis uses SSL (port 6380) for encrypted transport, password authentication, and sits within the Azure VNet — external access is not possible.

**Q: Why aren't some APIs cached?**  
A: Write-operation APIs (`/api/verify`, `/api/track`, `/api/contact`) don't need caching. `/api/admin/visitors` and `/api/admin/export` have pagination/filtering and low frequency, so they're also not cached.
