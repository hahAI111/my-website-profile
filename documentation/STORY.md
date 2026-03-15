# From Zero to Production: Building a Full-Stack Azure Portfolio Website Solo

> **Author**: AimeeWang — Microsoft Technical Support Engineer (AI)  
> **Repository**: [github.com/hahAI111/aimeewebpage](https://github.com/hahAI111/aimeewebpage)  
> **Live Site**: [aimeelan.azurewebsites.net](https://aimeelan.azurewebsites.net)

---

## Preface

This isn't a tutorial — it's the real story of a project.

Starting from "I want a website," this project evolved into a full-stack application with visitor verification, a blog system, GitHub project sync, admin analytics dashboard, Redis caching, PostgreSQL database, and CI/CD auto-deployment — step by step, including every pitfall and its solution.

**This project showcases not just the final product, but the problem-solving process behind it.**

---

## Table of Contents

- [Chapter 1: The Starting Point — A Single Request](#chapter-1-the-starting-point--a-single-request)
- [Chapter 2: From Static Pages to Flask Backend](#chapter-2-from-static-pages-to-flask-backend)
- [Chapter 3: Going Cloud — Migrating to Azure](#chapter-3-going-cloud--migrating-to-azure)
- [Chapter 4: The First Major Pitfall — The Connection String Mystery](#chapter-4-the-first-major-pitfall--the-connection-string-mystery)
- [Chapter 5: Git & Deployment — Automating the Release Process](#chapter-5-git--deployment--automating-the-release-process)
- [Chapter 6: Feature Explosion — Four Modules in One Release](#chapter-6-feature-explosion--four-modules-in-one-release)
- [Chapter 7: Polish — Consistency & Brand Unification](#chapter-7-polish--consistency--brand-unification)
- [Chapter 8: 503 — The Site Went Down](#chapter-8-503--the-site-went-down)
- [Chapter 9: Automation — Self-Syncing GitHub Projects](#chapter-9-automation--self-syncing-github-projects)
- [Chapter 10: 409 Deployment Conflict — Pipeline Collision](#chapter-10-409-deployment-conflict--pipeline-collision)
- [Chapter 11: Documentation as Product](#chapter-11-documentation-as-product)
- [Tech Stack Overview](#tech-stack-overview)
- [Final Project Structure](#final-project-structure)
- [Skills Demonstrated](#skills-demonstrated)
- [Final Thoughts](#final-thoughts)

---

## Chapter 1: The Starting Point — A Single Request

**Requirement**: "Help me build a website."

That's it. No design mockups, no requirements document, no tech review meeting.

**Approach**: Build a Minimum Viable Product (MVP) first — a clean personal introduction page.

**Plan**:
- Start with pure frontend: HTML + CSS + JavaScript
- Responsive design for mobile and desktop
- Include: self-introduction, skills showcase, contact info

```
Initial file structure:
static/
├── index.html    ← Main page
├── style.css     ← Styles
└── script.js     ← Interactions
```

**Skills**: HTML5 semantics, CSS Flexbox/Grid layout, responsive design, DOM manipulation

---

## Chapter 2: From Static Pages to Flask Backend

After the static page was done, new requirements appeared:

> "I need visitor verification, click tracking, a contact form, anti-phishing email detection, social links, email notifications..."

Pure frontend can't handle these. A backend was needed.

**Tech Choices**:
- **Language**: Python (my strongest language)
- **Framework**: Flask (lightweight, flexible, sufficient)
- **Database**: SQLite first (easy for development, swap later)

**Design**:
```
Browser → Flask API → SQLite
           │
           ├── /api/verify   → Visitor registration & verification
           ├── /api/track    → Click behavior tracking
           ├── /api/contact  → Messages + email notification
           └── /              → Static file server
```

**Security design** (built in from the start, not an afterthought):
- Block disposable email domains (tempmail.com, mailinator.com, etc. — 15 domains)
- Email format regex validation
- IP address SHA-256 hashed storage (privacy protection — raw IPs never stored)
- User-Agent truncated to 500 characters (prevents oversized string attacks)

**Skills**: Python Flask, RESTful API design, SQLite, SMTP email, security-first mindset

---

## Chapter 3: Going Cloud — Migrating to Azure

It worked great locally, but a personal website can't run on your own machine forever. Time to go to Azure.

**Why Azure?** I work at Microsoft, I'm most familiar with Azure, and I can leverage company resources to learn.

**Architecture upgrade**:

```
Before: Flask → SQLite (single-file database)
After:  Flask → Azure PostgreSQL (cloud database)
                → Azure Redis (cache layer)
                → Azure App Service (managed hosting)
```

**Azure resources created**:

| Resource | Name | Spec | Purpose |
|---|---|---|---|
| App Service | aimeelan | Linux, Python 3.14 | Run Flask application |
| PostgreSQL Flexible Server | aimeelan-server | | Persistent data storage |
| Azure Cache for Redis | aimee-cache | Basic SKU | Cache acceleration |

**Code changes**:
- `sqlite3` → `psycopg2` (PostgreSQL driver)
- `?` placeholders → `%s` (PostgreSQL syntax)
- `lastrowid` → `RETURNING id` (PostgreSQL feature)
- Added `redis` cache layer
- Added `sslmode="require"` (Azure enforces SSL)

**Skills**: Azure cloud services, SQLite→PostgreSQL migration, database dialect differences, SSL connections, Redis cache architecture

---

## Chapter 4: The First Major Pitfall — The Connection String Mystery

### Problem

After deploying to Azure, the website wouldn't load. 504 Gateway Timeout.

### Investigation

1. **Check code**: Works locally ✓
2. **Check Azure config**: App Service running ✓
3. **Check database**: Azure PostgreSQL online ✓
4. **Check logs**: `psycopg2.OperationalError: connection failed`

The issue was the **connection string format**.

### Root Cause

Azure Portal provides connection strings in **ADO.NET format** (designed for C#):
```
Server=aimeelan-server.postgres.database.azure.com;Database=aimeelan-database;Port=5432;User Id=xxx;Password=xxx;
```

But Python's psycopg2 requires **libpq format**:
```
host=aimeelan-server.postgres.database.azure.com dbname=aimeelan-database user=xxx password=xxx
```

Redis had the same problem — Azure's format doesn't match what the Python redis library expects.

### Solution

Wrote two parser functions to automatically convert formats:

```python
def _parse_pg_conn(raw):
    """ADO.NET format → libpq format"""
    if not raw or raw.startswith("host="):
        return raw  # Already in correct format
    parts = dict(p.split("=", 1) for p in raw.split(";") if "=" in p)
    return f"host={parts['Server']} dbname={parts['Database']} user={parts['User Id']} password={parts['Password']}"

def _parse_redis_conn(raw):
    """Azure Redis format → redis:// URI format"""
    # aimee-cache.redis.cache.windows.net:6380,password=xxx,ssl=True
    # → rediss://:xxx@aimee-cache.redis.cache.windows.net:6380/0
```

### Lesson Learned

> **Azure-provided connection strings may not work out of the box.** Different languages and drivers require different formats.
> When facing connection failures, the first step: **print the connection string format and compare it with the driver documentation.**

**Skills**: Problem diagnosis, log analysis, connection string parsing, Azure Service Connector understanding

---

## Chapter 5: Git & Deployment — Automating the Release Process

### Initializing Git

```bash
git init
git remote add origin https://github.com/hahAI111/aimeewebpage.git
```

The very first push hit an issue — Azure had already auto-created a workflow file in the repo, causing `git push` to be rejected (both sides had independent commit histories).

**Solution**:
```bash
git pull origin main --allow-unrelated-histories  # Merge two unrelated histories
git push origin main
```

### CI/CD Pipeline

Azure automatically generated a GitHub Actions config file (`.github/workflows/main_aimeelan.yml`) when creating the App Service.

From then on, every `git push` to the main branch:
1. GitHub Actions pulls the latest code
2. Installs Python + dependencies on an Ubuntu VM
3. Packages and uploads the code to Azure App Service
4. Azure automatically restarts the application

**From writing code to going live — just one `git push` command.**

**Skills**: Git version control, GitHub Actions CI/CD, OIDC authentication, automated deployment

---

## Chapter 6: Feature Explosion — Four Modules in One Release

After the basic site went live, four major features were planned at once:

### 1. Admin Analytics Dashboard

```
GET /api/admin/stats → 8 SQL queries → Chart.js visualization

Includes:
├── KPI cards (visitors / PVs / clicks / messages)
├── 30-day visitor trend line chart
├── 30-day PV trend line chart
├── Top 15 clicked elements bar chart
├── Top 10 pages with average duration
├── Email domain distribution (visitor company insights)
├── Device type distribution pie chart (Mobile/Tablet/Desktop)
├── Recent messages list
├── Top blog posts ranking
└── Retention analysis (Day 0/1/7/30 return rates)
```

**SQL highlight**: The retention analysis uses CTEs (WITH clauses) + conditional counting + date arithmetic — the most complex query in the entire project.

### 2. Blog CMS System

Designed a complete content management model:

```
posts (articles) ←→ post_tags (junction table) ←→ tags

Features:
├── Markdown rendering (marked.js + highlight.js code highlighting)
├── Tag filtering
├── Paginated queries
├── View counter
└── 5 seed articles (Azure AI, Python tools, PostgreSQL optimization, networking, career)
```

### 3. GitHub Project Showcase

```
GitHub API → projects table → /projects page

Features:
├── Auto-fetch GitHub repository info
├── Display language, stars, forks, last updated
├── Upsert sync (ON CONFLICT DO UPDATE)
└── Featured project pinning
```

### 4. Frontend Page Tracking

```javascript
// script.js — fires automatically on every page load
fetch('/api/pageview', {
  method: 'POST',
  body: JSON.stringify({ page, referrer, screen_width, duration_sec })
});
```

### Redis Cache Strategy

Not all APIs are cached — only **read-heavy, write-light** endpoints:

| Endpoint | Cached | TTL | Reason |
|---|---|---|---|
| Post list | ✓ | 120s | Frequently accessed, data changes slowly |
| Post detail | ✓ | 300s | Content rarely changes |
| Tag list | ✓ | 300s | Almost never changes |
| Project list | ✓ | 300s | Updates every 6 hours |
| Admin stats | ✓ | 60s | Needs near real-time |
| Retention analysis | ✓ | 300s | Heavy query, results change slowly |
| Visitor registration | ✗ | — | Write operation |
| Page tracking | ✗ | — | Write operation |

**Cache invalidation**: New message → clear `stats:*`; Project sync → clear `projects:*`.

### Database Design

Created 9 tables + 6 indexes in one go:

```
visitors ──→ click_logs, messages, page_views, visitor_sessions
posts ──→ post_tags ←── tags
projects (standalone table)
```

All CREATE TABLE statements use `IF NOT EXISTS`, seed data uses `ON CONFLICT DO NOTHING` — safe to restart repeatedly.

**Skills**: Complex SQL (CTEs, Window Functions, aggregation), database schema design, many-to-many relationships, Redis cache strategy, Chart.js data visualization, Markdown rendering, RESTful API design

---

## Chapter 7: Polish — Consistency & Brand Unification

After features were complete, two UI issues were discovered:

### Issue 1: Inconsistent Navigation Bar

| Page | Nav Links |
|---|---|
| index.html | Home, About, Skills, Contact, Blog, Projects ✓ |
| blog.html | Home, Blog, Projects ✗ |
| projects.html | Home, Blog, Projects ✗ |
| post.html | Home, Blog, Projects ✗ |
| admin.html | Home, Blog, Projects ✗ |

Blog/Projects pages only had 3 nav links while the homepage had 6.

### Issue 2: Inconsistent Name

Some pages showed "Jing Wang", others "JW" — needed to unify to "AimeeWang".

### Solution

Modified all 5 HTML files at once to unify navigation and naming.

**This seemingly minor consistency issue reflects product awareness** — users don't just look at one page.

**Skills**: Frontend consistency, brand awareness, batch file editing

---

## Chapter 8: 503 — The Site Went Down

### Problem

After pushing the nav bar fix, the website showed:

```
:( Application Error
If you are the application administrator, you can access the diagnostic resources.
```

HTTP 503 — the site was completely down.

### Investigation

1. Testing individual URLs:
   - `/` → 200 ✓ (verify.html — static file)
   - `/blog` → 503 ✗
   - `/projects` → 503 ✗
   - `/api/posts` → 200 ✓ (Flask API working)
   - `/blog.html` → 200 ✓ (static file working)

2. Pattern identified:
   - Static file serving → working
   - Flask API routes → working
   - Flask routes that return static files (`/blog`, `/projects`) → 503

3. After waiting a few minutes, all routes recovered.

### Root Cause

**Not a code issue.** 503 was a temporary state during Azure App Service deployment. We had pushed multiple times in quick succession (feature code, nav fix, auto-sync), causing frequent App Service restarts.

### Lesson Learned

> **503 doesn't always mean a code bug.** The site may be briefly unavailable during deployment — this is normal.
> Multiple rapid pushes cause multiple redeployments, making it worse.
> **Best practice: batch changes into a single commit before pushing.**

**Skills**: Production debugging, HTTP status code analysis, deployment process understanding, calm analysis instead of blindly changing code

---

## Chapter 9: Automation — Self-Syncing GitHub Projects

### Problem

After creating new repositories on GitHub, the Projects page on the website didn't automatically update. The sync only triggered once on first startup (when the projects table was empty).

### Approach Comparison

| Approach | Pros | Cons |
|---|---|---|
| A: Scheduled background sync | Simple, no external config needed | Has delay (up to 6 hours) |
| B: GitHub Webhook | Real-time, precise | Requires Webhook URL config, signature verification |

Chose **Approach A**: Use Python `threading` to create a daemon thread that pulls GitHub API every 6 hours.

```python
def _github_sync_loop():
    while True:
        time.sleep(GITHUB_SYNC_INTERVAL)  # Default 21600 seconds = 6 hours
        _seed_github_projects()            # Reuse existing sync function
        cache_delete("projects:*")         # Clear cache

_sync_thread = threading.Thread(target=_github_sync_loop, daemon=True)
_sync_thread.start()
```

`daemon=True` ensures the thread stops automatically when the main process exits, preventing it from blocking App Service restarts. The sync interval is configurable via the `GITHUB_SYNC_INTERVAL` environment variable.

**Skills**: Multi-threaded programming, background task scheduling, daemon threads, API integration, configurable design

---

## Chapter 10: 409 Deployment Conflict — Pipeline Collision

### Problem

After pushing, GitHub Actions showed red:

```
Error: Failed to deploy web package using OneDeploy to App Service.
Conflict (CODE: 409)
```

### Analysis

409 Conflict = Azure App Service has a deployment in progress and won't accept new deployment requests.

Cause: We had pushed REDIS.md, POSTGRESQL.md, and auto-sync code in rapid succession. Each push triggered a deployment, and new deployments arrived before previous ones finished — **a collision.**

```
Deploy #9  (REDIS.md)       ──→ Success ✓
Deploy #10 (POSTGRESQL.md)  ──→ Success ✓ (previous just finished)
Deploy #11 (auto-sync code) ──→ 409 ✗ (#10's Azure build still running)
Deploy #12 (retry)          ──→ Success ✓ (#10 finally completed)
Deploy #13 (retry)          ──→ 409 ✗ (residual lock)
Deploy #14 (after restart)  ──→ Success ✓
```

### Solution

```bash
# 1. Restart App Service to clear the deployment lock
az webapp restart --name aimeelan --resource-group aimee-test-env

# 2. Wait for restart to complete
Start-Sleep -Seconds 10

# 3. Empty commit to re-trigger deployment
git commit --allow-empty -m "Retry deploy after restart"
git push origin main
```

### Lesson Learned

> **CI/CD pipelines can have "traffic accidents" too.** Just like code, deployments need to account for concurrency.
> Frequent small pushes trigger many deployments — batching is better.

**Skills**: CI/CD troubleshooting, Azure CLI operations, deployment pipeline understanding, 409 status code

---

## Chapter 11: Documentation as Product

Code alone isn't enough. A good project needs good documentation.

Why write documentation?
1. **For yourself** — You'll still understand it three months later
2. **For others** — Anyone can quickly understand the project
3. **To showcase ability** — Proves you can think systematically, not just write code

The final project includes 10 documents (all in `docs/`):

| Document | Content | Target Audience |
|---|---|---|
| README.md | Project overview, quick start | Everyone |
| ARCHITECTURE.md | System architecture, security design | Engineers |
| POSTGRESQL.md | Database schema, SQL deep dive, monitoring | Backend developers |
| REDIS.md | Cache strategy, monitoring, testing methods | Backend developers |
| DEPLOYMENT.md | CI/CD pipeline end-to-end | DevOps |
| TROUBLESHOOTING.md | Issue resolution guide | Operations |
| STORY.md | The document you're reading now | Everyone |
| AZURE_SETUP_GUIDE.md | Azure resource provisioning walkthrough | DevOps |
| BACKUP_AND_MIGRATION.md | Database backup & migration procedures | Operations |
| HOW_TO_DEPLOY.md | Step-by-step deployment guide | DevOps |

**Skills**: Technical writing, systematic thinking, documentation structure design

---

## Tech Stack Overview

```
Frontend:  HTML5 / CSS3 / JavaScript / Chart.js / marked.js / highlight.js
Backend:   Python / Flask / gunicorn
Database:  Azure PostgreSQL Flexible Server / psycopg2
Cache:     Azure Cache for Redis
Cloud:     Azure App Service (Linux)
CI/CD:     GitHub Actions / Azure OneDeploy
VCS:       Git / GitHub
Security:  SSL/TLS / email validation / IP hashing / bcrypt password hashing / disposable email blocking
Monitoring: Azure Metrics / Redis MONITOR / PostgreSQL pg_stat
```

---

## Final Project Structure

```
my-website/
├── .github/
│   └── workflows/
│       └── main_aimeelan.yml     ← CI/CD pipeline config
├── static/
│   ├── index.html                ← Homepage (intro, skills, contact)
│   ├── verify.html               ← Visitor verification gate
│   ├── blog.html                 ← Blog listing page
│   ├── post.html                 ← Blog post detail page
│   ├── projects.html             ← GitHub project showcase page
│   ├── admin.html                ← Admin analytics dashboard
│   ├── style.css                 ← Global styles
│   └── script.js                 ← Page tracking + interactions
├── docs/
│   ├── ARCHITECTURE.md           ← System architecture & security design
│   ├── AZURE_SETUP_GUIDE.md     ← Azure resource provisioning walkthrough
│   ├── BACKUP_AND_MIGRATION.md  ← Database backup & migration procedures
│   ├── DEPLOYMENT.md             ← CI/CD pipeline documentation
│   ├── HOW_TO_DEPLOY.md         ← Step-by-step deployment guide
│   ├── POSTGRESQL.md             ← Database documentation
│   ├── REDIS.md                  ← Cache documentation
│   ├── STORY.md                  ← Project story (this document)
│   ├── TROUBLESHOOTING.md       ← Troubleshooting guide
│   └── REDIS_ADMIN_SCREENSHOT.png
├── tests/
│   └── test_app.py               ← 50 unit tests
├── screenshots/                   ← Feature screenshots
├── app.py                        ← Flask backend (all APIs + DB)
├── seed_data.py                  ← Database seed data
├── requirements.txt              ← Python dependencies
└── README.md                     ← Project overview
```

---

## Skills Demonstrated

### Backend Development
- Python Flask framework, RESTful API design
- PostgreSQL complex queries (CTEs, Window Functions, aggregation, Upsert)
- Redis cache strategy design (Read-Through, TTL, active invalidation)
- Multi-threaded background task scheduling
- SMTP email notification integration

### Frontend Development
- Responsive HTML/CSS layouts
- JavaScript async programming (fetch API)
- Chart.js data visualization
- Real-time Markdown rendering

### Cloud Computing & DevOps
- Azure App Service / PostgreSQL / Redis deployment & configuration
- GitHub Actions CI/CD automated pipeline
- Connection string format conversion (ADO.NET → libpq / Redis URI)
- Azure Metrics monitoring & alerting

### Security Engineering
- SSL/TLS encrypted communication
- bcrypt password hashing
- IP privacy protection (SHA-256 hashed storage)
- Disposable email domain blocking
- SQL injection prevention (parameterized queries + allowlisting)
- Session management & admin authentication

### Problem Solving
- 504 timeout → connection string format mismatch
- 503 application error → transient deployment state
- 409 deployment conflict → App Service deployment lock
- Git merge conflict → `--allow-unrelated-histories`
- UI inconsistency → systematic batch fix

### System Design
- 9-table relational database schema
- 6 indexes for performance optimization
- Read/write separated cache strategy
- Graceful degradation (Redis failure doesn't affect core functionality)
- Configurable design (all sensitive configs injected via environment variables)

### Technical Writing
- 7 systematic documents
- Diagrams, tables, code examples
- Layered documentation for different audiences

---

## Final Thoughts

This project, from the first line of HTML to its final version, went through:

- **16 Git commits**
- **9 database tables**
- **1,200+ lines of Python backend code**
- **7 HTML pages**
- **7 technical documents**
- **4 deployment failures and fixes**
- **Countless moments of "why isn't this working?" followed by "so that's why!"**

Every problem was encountered in real time, and every solution was figured out on the spot. There's no perfect code — only a continuous process of improvement.

> **The most valuable part of a project isn't the final result — it's every step taken to solve the problems along the way.**
