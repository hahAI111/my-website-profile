# Flask — How It Powers This Project

Flask is the **core backend framework** for the entire application. All HTTP handling — routing, request parsing, JSON responses, session management, and static file serving — lives in a single file: `app.py`.

---

## Table of Contents

- [Initialization](#initialization)
- [Imported Flask Components](#imported-flask-components)
- [Route Overview](#route-overview)
  - [Static Page Routes](#static-page-routes)
  - [Visitor API Routes](#visitor-api-routes)
  - [Blog API Routes](#blog-api-routes)
  - [Project API Routes](#project-api-routes)
  - [Admin API Routes](#admin-api-routes)
- [Custom Middleware (Decorators)](#custom-middleware-decorators)
- [Request Flow](#request-flow)
- [How Routes Are Triggered](#how-routes-are-triggered)
  - [User Click / Navigation](#1-user-click--navigation)
  - [JavaScript AJAX Calls](#2-javascript-ajax-calls)
- [App Startup](#app-startup)

---

## Initialization

```python
from flask import Flask, request, jsonify, send_from_directory, session, redirect, Response, make_response

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
```

- `static_folder="static"` — Serves HTML/CSS/JS from the `static/` directory
- `secret_key` — Used for encrypting Flask sessions (cookie-based)

---

## Imported Flask Components

| Component | Purpose |
|-----------|---------|
| `Flask` | Application instance |
| `request` | Access incoming request data (JSON body, query params, headers, client IP) |
| `jsonify` | Return JSON responses with proper `Content-Type` |
| `session` | Server-side session for login state and visitor verification |
| `send_from_directory` | Serve static HTML files (verify.html, index.html, blog.html, etc.) |
| `redirect` | HTTP redirects |
| `Response` | Custom response objects |
| `make_response` | Build responses with custom headers (used for CSV export) |

---

## Route Overview

The application defines **22 routes** across 5 categories:

### Static Page Routes

These serve HTML pages when users navigate the site:

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Landing page — serves `verify.html` or `index.html` based on session |
| `/blog` | GET | Blog listing page |
| `/blog/<slug>` | GET | Individual blog post page |
| `/projects` | GET | GitHub projects showcase page |
| `/admin` | GET | Admin dashboard page |
| `/<path:filename>` | GET | Catch-all for other static files (CSS, JS, images) |

### Visitor API Routes

Handle visitor verification and tracking:

| Route | Method | Auth | Description |
|-------|--------|------|-------------|
| `/api/verify` | POST | — | Verify visitor name + email, create session |
| `/api/pageview` | POST | — | Record a page view with analytics data |
| `/api/track` | POST | Verified | Log a click event on any `data-track` element |
| `/api/contact` | POST | Verified | Submit a message to site owner (saved to DB + email notification) |

### Blog API Routes

Serve blog content as JSON:

| Route | Method | Description |
|-------|--------|-------------|
| `/api/posts` | GET | List blog posts (supports `?tag=`, `?page=`, `?per_page=` query params) |
| `/api/posts/<slug>` | GET | Get a single post with full Markdown content |
| `/api/tags` | GET | List all tags with post counts |

### Project API Routes

GitHub project integration:

| Route | Method | Auth | Description |
|-------|--------|------|-------------|
| `/api/projects` | GET | — | List all synced GitHub projects |
| `/api/projects/sync` | POST | Admin | Sync repositories from GitHub API |

### Admin API Routes

Dashboard and data management:

| Route | Method | Auth | Description |
|-------|--------|------|-------------|
| `/api/admin/login` | POST | — | Admin login (bcrypt password verification) |
| `/api/admin/logout` | POST | — | Admin logout (clear session) |
| `/api/admin/stats` | GET | Admin | Full analytics dashboard data (8 SQL queries + Redis server info) |
| `/api/admin/visitors` | GET | Admin | Paginated visitor list with domain filter |
| `/api/admin/export/<table>` | GET | Admin | CSV export (visitors, click_logs, messages, page_views) |
| `/api/admin/retention` | GET | Admin | Retention cohort analysis (CTE query) |

---

## Custom Middleware (Decorators)

Two permission decorators built on Flask `session`:

### `@require_verified`
```python
def require_verified(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("verified"):
            return jsonify({"error": "Not verified"}), 403
        return f(*args, **kwargs)
    return decorated
```
Applied to routes that require visitor verification (e.g., `/api/track`, `/api/contact`).

### `@require_admin`
```python
def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"error": "Admin login required"}), 401
        return f(*args, **kwargs)
    return decorated
```
Applied to all admin-only routes (stats, visitors, export, retention, project sync).

---

## Request Flow

```
User action in browser
       │
       ▼
Browser sends HTTP request (GET / POST)
       │
       ▼
Flask @app.route receives and dispatches
       │
       ▼
Decorator checks auth (if required)
       │
       ├── 401/403 → Return error JSON
       │
       ▼
Route function executes:
       ├── Check Redis cache (cache_get)
       │     ├── Hit → Return cached data
       │     └── Miss ──┐
       │                ▼
       ├── Query PostgreSQL (psycopg2)
       ├── Write to Redis cache (cache_set)
       │
       ▼
Return HTML page or JSON response
       │
       ▼
Browser renders page / JS updates DOM
```

---

## How Routes Are Triggered

### 1. User Click / Navigation

When a user clicks a link or enters a URL, the browser sends a GET request. Flask returns an HTML page:

| User Action | HTTP Request | Flask Returns |
|-------------|-------------|---------------|
| Opens website | `GET /` | `verify.html` or `index.html` |
| Clicks "Blog" | `GET /blog` | `blog.html` |
| Clicks a blog post | `GET /blog/my-post` | `post.html` |
| Clicks "Projects" | `GET /projects` | `projects.html` |
| Clicks "Admin" | `GET /admin` | `admin.html` |

### 2. JavaScript AJAX Calls

After a page loads, frontend JavaScript (`script.js`) automatically calls API endpoints. Flask returns JSON data:

| Trigger | HTTP Request | Purpose |
|---------|-------------|---------|
| User submits verification form | `POST /api/verify` | Validate name + email |
| Page load (automatic) | `POST /api/pageview` | Record page view analytics |
| User clicks any `data-track` element | `POST /api/track` | Log click behavior |
| User submits contact form | `POST /api/contact` | Send message |
| `blog.html` loads | `GET /api/posts` | Fetch post list |
| `post.html` loads | `GET /api/posts/<slug>` | Fetch post content |
| `projects.html` loads | `GET /api/projects` | Fetch project list |
| Admin clicks "Sync" button | `POST /api/projects/sync` | Sync from GitHub |
| `admin.html` loads | `GET /api/admin/stats` | Fetch dashboard data |
| Admin clicks "Export" | `GET /api/admin/export/<table>` | Download CSV |

---

## App Startup

**Local development:**
```python
if __name__ == "__main__":
    app.run(debug=True, port=5000)
```
Run with `python app.py` → available at `http://localhost:5000`

**Azure production:**
```bash
gunicorn --bind=0.0.0.0:8000 --timeout 600 app:app
```
- `app:app` = import the `app` object from `app.py`
- gunicorn spawns multiple workers, each running the Flask app
- Azure App Service proxies incoming HTTPS traffic to port 8000

---

## Summary

Flask serves as the **central hub** of this application:

```
┌─────────────────────────────────────────┐
│              Browser (Client)           │
│  verify.html / index.html / blog.html  │
│  script.js → AJAX calls                │
└──────────────┬──────────────────────────┘
               │ HTTP requests
               ▼
┌─────────────────────────────────────────┐
│          Flask (app.py)                 │
│  22 routes · 2 auth decorators         │
│  Session management · JSON responses   │
├──────────────┬──────────────────────────┤
│              │                          │
│    ┌─────────▼────────┐  ┌────────────┐│
│    │   PostgreSQL      │  │   Redis    ││
│    │   9 tables        │  │   Cache    ││
│    │   (persistent)    │  │   (fast)   ││
│    └──────────────────┘  └────────────┘│
└─────────────────────────────────────────┘
```

All data flows through Flask — it receives every browser request, applies authentication, queries the database (with Redis caching), and returns the result.
