# Aimee's Portfolio Website

A full-stack personal portfolio website with admin dashboard, visitor analytics, blog CMS, GitHub project showcase, click tracking, contact form, and email notifications.

**Live Site:** https://aimeelan.azurewebsites.net

## Screenshots

| Visitor Verification | Blog |
|:---:|:---:|
| ![Verify](screenshots/01-verify.png) | ![Blog](screenshots/02-blog.png) |

| GitHub Projects | Admin Dashboard |
|:---:|:---:|
| ![Projects](screenshots/03-projects.png) | ![Admin](screenshots/04-admin.png) |

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Backend | Python Flask | Web framework, API routes, session management |
| Database | Azure PostgreSQL Flexible Server | Persistent data: visitors, analytics, blog posts, projects |
| Cache | Azure Cache for Redis | Cache stats, blog posts, reduce DB queries |
| Frontend | HTML / CSS / JavaScript | Dark-theme portfolio UI with Chart.js dashboards |
| Hosting | Azure App Service (Linux) | Production hosting with managed SSL |
| CI/CD | GitHub Actions | Auto build & deploy on `git push` |
| Email | Gmail SMTP | Notify site owner when visitors send messages |
| External API | GitHub REST API v3 | Sync repos for project showcase |

## Project Structure

```
my-website/
├── app.py                  # Flask backend (all API routes, DB, auth)
├── seed_data.py            # Blog seed posts (loaded on first startup)
├── requirements.txt        # Python dependencies (version-pinned)
├── .env.example            # Environment variable template
├── .gitignore
├── LICENSE
├── README.md
├── static/
│   ├── verify.html         # Entry gate — name + email verification
│   ├── index.html          # Main portfolio page (after verification)
│   ├── blog.html           # Blog listing with tag filtering & pagination
│   ├── post.html           # Individual blog post (Markdown + code highlight)
│   ├── projects.html       # GitHub project showcase
│   ├── admin.html          # Admin dashboard (login, charts, tables, export)
│   ├── style.css           # Dark theme with purple accents
│   └── script.js           # Click tracking, pageview tracking, animations
├── tests/
│   └── test_app.py         # 50 unit tests (email, auth, routes, cache, parsers)
├── docs/                   # Architecture & component documentation
├── guides/                 # Deployment & migration guides
├── tutorials/              # Step-by-step Azure setup tutorial
├── screenshots/            # Website screenshots for README
└── .github/
    └── workflows/
        └── main_aimeelan.yml   # GitHub Actions CI/CD pipeline
```

## Features

### Core
- **Visitor Verification** — Visitors must enter name + email before viewing the portfolio
- **Anti-Phishing** — Disposable/temporary email domains are blocked
- **Click Tracking** — Every `data-track` click is logged with visitor ID and page
- **Contact Form** — Messages saved to DB + email notification to owner

### Admin Dashboard (`/admin`)
- **Secure Login** — bcrypt password hashing, session-based auth
- **KPI Cards** — Visitors, page views, clicks, messages, blog post counts
- **Charts** — Visitors/day, pageviews/day, top clicks, device breakdown, email domains, top pages (Chart.js)
- **Visitor List** — Pagination, domain filtering
- **Retention Cohorts** — Day 0/1/7/30 retention analysis with SQL CTEs
- **CSV Export** — Download visitors, clicks, messages, page views as CSV
- **GitHub Sync** — One-click sync of repos from GitHub API

### Visitor Analytics
- **Page View Tracking** — Page, referrer, user-agent, IP hash, screen width, duration
- **Session Management** — Tracks visitor sessions with page count and timestamps
- **Device Classification** — Mobile / Tablet / Desktop based on screen width

### Blog CMS (`/blog`)
- **5 Seed Posts** — Azure AI Support, Python diagnostic tools, PostgreSQL optimization, Azure networking, career growth
- **Markdown Rendering** — Using marked.js with highlight.js code syntax highlighting
- **Tag Filtering** — Filter posts by tags (Azure, AI, Python, SQL, etc.)
- **Pagination** — Server-side pagination with configurable page size
- **View Counter** — Auto-increments on each post view

### GitHub Projects (`/projects`)
- **GitHub API Integration** — Sync repos via `/api/projects/sync`
- **Project Cards** — Name, description, language, stars, forks, issues
- **Featured Projects** — Highlight featured repos
- **Live Demo Links** — Shows homepage URL if set on GitHub

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | — | Serves verify.html or index.html based on session |
| GET | `/blog` | — | Blog listing page |
| GET | `/blog/<slug>` | — | Individual blog post page |
| GET | `/projects` | — | GitHub projects showcase page |
| GET | `/admin` | — | Admin dashboard page |
| POST | `/api/verify` | — | Verify visitor (name + email) |
| POST | `/api/pageview` | — | Record a page view with analytics data |
| POST | `/api/track` | Verified | Log a click event |
| POST | `/api/contact` | Verified | Send a message to site owner |
| GET | `/api/posts` | — | List blog posts (supports `?tag=`, `?page=`, `?per_page=`) |
| GET | `/api/posts/<slug>` | — | Get single post with full Markdown content |
| GET | `/api/tags` | — | List all tags with post counts |
| GET | `/api/projects` | — | List all synced GitHub projects |
| POST | `/api/projects/sync` | Admin | Sync repos from GitHub API |
| POST | `/api/admin/login` | — | Admin login (bcrypt) |
| POST | `/api/admin/logout` | — | Admin logout |
| GET | `/api/admin/stats` | Admin | Full analytics dashboard data |
| GET | `/api/admin/visitors` | Admin | Paginated visitor list with domain filter |
| GET | `/api/admin/export/<table>` | Admin | CSV export (visitors, click_logs, messages, page_views) |
| GET | `/api/admin/retention` | Admin | Retention cohort analysis |

## Database Tables

| Table | Purpose |
|-------|---------|
| `visitors` | Verified visitors (name, email, token) |
| `click_logs` | Click tracking events |
| `messages` | Contact form messages |
| `page_views` | Page view analytics (page, referrer, UA, IP hash, duration, screen width) |
| `visitor_sessions` | Session lifecycle (start, end, page count) |
| `posts` | Blog posts (slug, title, summary, Markdown content, views) |
| `tags` | Blog tags |
| `post_tags` | Many-to-many: posts ↔ tags |
| `projects` | GitHub repos (name, description, language, stars, forks, featured) |

## Quick Start (Local Development)

```bash
# 1. Clone
git clone https://github.com/hahAI111/aimeewebpage.git
cd aimeewebpage

# 2. Copy environment template and edit
cp .env.example .env
# Edit .env with your PostgreSQL connection string (at minimum)

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run (uses local PostgreSQL by default)
python app.py
# → http://localhost:5000
```

## Running Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

50 tests covering: email validation, IP hashing, connection string parsing, cache helpers, seed data integrity, Flask routes, auth, and pageview tracking.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `AZURE_POSTGRESQL_CONNECTIONSTRING` | PostgreSQL connection string |
| `REDISCACHECONNSTR_azure_redis_cache` | Redis connection string |
| `OWNER_EMAIL` | Email to receive contact notifications |
| `SMTP_SERVER` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` | Gmail SMTP config |
| `SECRET_KEY` | Flask session encryption key |
| `ADMIN_USER` | Admin username (default: `admin`) |
| `ADMIN_PASS` or `ADMIN_PASS_HASH` | Admin password (plain or bcrypt hash) |
| `GITHUB_USERNAME` | GitHub user for project sync (default: `hahAI111`) |
| `GITHUB_TOKEN` | GitHub personal access token (optional, raises API rate limit) |

## Deployment

Code is auto-deployed via GitHub Actions. Just push to `main`:

```bash
git add -A
git commit -m "your change"
git push
```

GitHub Actions will build and deploy to Azure App Service automatically.

## Related Docs

All documentation is in the [`docs/`](docs/) folder:

- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — System architecture, database design, data flow diagrams
- [FLASK.md](docs/FLASK.md) — How Flask powers the backend: all 22 routes, auth decorators, request flow
- [DEPLOYMENT.md](docs/DEPLOYMENT.md) — CI/CD pipeline, GitHub Actions workflow, deployment guide
- [POSTGRESQL.md](docs/POSTGRESQL.md) — Database schema, SQL operations, monitoring & maintenance
- [REDIS.md](docs/REDIS.md) — Cache strategy, core functions, Azure Redis monitoring
- [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — Issues encountered during development and solutions
- [STORY.md](docs/STORY.md) — The full project journey from scratch to production

### Guides (in [`guides/`](guides/))

- [BACKUP_AND_MIGRATION.md](guides/BACKUP_AND_MIGRATION.md) — What to back up, what you'll lose, and how to migrate to a new platform
- [HOW_TO_DEPLOY.md](guides/HOW_TO_DEPLOY.md) — How to run the code locally and deploy to Railway, Render, Azure, or any VPS

### Tutorials (in [`tutorials/`](tutorials/))

- [AZURE_SETUP_GUIDE.md](tutorials/AZURE_SETUP_GUIDE.md) — Step-by-step Azure cloud setup: Resource Group, VNet, PostgreSQL, Redis, App Service, CI/CD, monitoring, and cost estimation
