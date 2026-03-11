import os
import re
import json
import secrets
import hashlib
import smtplib
import csv
import io
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, session, redirect, Response, make_response
import psycopg2
import psycopg2.extras
import redis
import requests as http_requests
import bcrypt

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# ── Configuration ──────────────────────────────────────────
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "yourname@example.com")
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.example.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "yourname@example.com")
SMTP_PASS = os.environ.get("SMTP_PASS", "your-app-password")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS_HASH = os.environ.get("ADMIN_PASS_HASH", "")
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "hahAI111")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# ── Connection String Parsers ──────────────────────────────
def _parse_pg_conn(raw):
    if not raw or raw.startswith("host="):
        return raw
    parts = dict(p.split("=", 1) for p in raw.split(";") if "=" in p)
    return (
        f"host={parts.get('Server','')} "
        f"dbname={parts.get('Database','')} "
        f"user={parts.get('User Id','')} "
        f"password={parts.get('Password','')}"
    )

_raw_pg = (
    os.environ.get("AZURE_POSTGRESQL_CONNECTIONSTRING")
    or os.environ.get("CUSTOMCONNSTR_AZURE_POSTGRESQL_CONNECTIONSTRING")
    or "host=localhost dbname=portfoliodb user=postgres password=postgres"
)
DATABASE_URL = _parse_pg_conn(_raw_pg)

def _parse_redis_conn(raw):
    if not raw or raw.startswith("redis"):
        return raw
    parts = dict(p.split("=", 1) for p in raw.split(",") if "=" in p)
    host_port = raw.split(",")[0]
    password = parts.get("password", "")
    use_ssl = parts.get("ssl", "False").lower() == "true"
    scheme = "rediss" if use_ssl else "redis"
    return f"{scheme}://:{password}@{host_port}/0"

_raw_redis = (
    os.environ.get("AZURE_REDIS_CONNECTIONSTRING")
    or os.environ.get("REDISCACHECONNSTR_azure_redis_cache")
    or ""
)
REDIS_URL = _parse_redis_conn(_raw_redis)

BLOCKED_DOMAINS = {
    "tempmail.com", "throwaway.email", "guerrillamail.com",
    "mailinator.com", "yopmail.com", "sharklasers.com",
    "guerrillamailblock.com", "grr.la", "dispostable.com",
    "trashmail.com", "10minutemail.com", "fakeinbox.com",
    "tempail.com", "getnada.com", "maildrop.cc",
}

# ── Redis Cache ────────────────────────────────────────────
redis_client = None
if REDIS_URL:
    try:
        redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
        print("Redis connected successfully")
    except Exception as e:
        print(f"Redis connection failed: {e}")
        redis_client = None

def cache_get(key):
    if redis_client:
        try:
            val = redis_client.get(key)
            return json.loads(val) if val else None
        except Exception:
            return None
    return None

def cache_set(key, value, ttl=300):
    if redis_client:
        try:
            redis_client.setex(key, ttl, json.dumps(value))
        except Exception:
            pass

def cache_delete(pattern):
    if redis_client:
        try:
            for key in redis_client.scan_iter(match=pattern):
                redis_client.delete(key)
        except Exception:
            pass

# ── Database (PostgreSQL) ──────────────────────────────────
def get_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS visitors (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            verified INTEGER DEFAULT 0,
            token TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS click_logs (
            id SERIAL PRIMARY KEY,
            visitor_id INTEGER REFERENCES visitors(id),
            element TEXT NOT NULL,
            page TEXT,
            clicked_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            visitor_id INTEGER REFERENCES visitors(id),
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            message TEXT NOT NULL,
            sent_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS page_views (
            id SERIAL PRIMARY KEY,
            visitor_id INTEGER REFERENCES visitors(id),
            page TEXT NOT NULL,
            referrer TEXT,
            user_agent TEXT,
            ip_hash TEXT,
            duration_sec INTEGER DEFAULT 0,
            screen_width INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS visitor_sessions (
            id SERIAL PRIMARY KEY,
            visitor_id INTEGER REFERENCES visitors(id),
            session_token TEXT UNIQUE,
            started_at TIMESTAMP DEFAULT NOW(),
            ended_at TIMESTAMP,
            page_count INTEGER DEFAULT 0
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id SERIAL PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            summary TEXT,
            content TEXT NOT NULL,
            status TEXT DEFAULT 'published',
            views INTEGER DEFAULT 0,
            published_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS post_tags (
            post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
            tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (post_id, tag_id)
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id SERIAL PRIMARY KEY,
            github_repo TEXT UNIQUE,
            name TEXT NOT NULL,
            description TEXT,
            language TEXT,
            stars INTEGER DEFAULT 0,
            forks INTEGER DEFAULT 0,
            open_issues INTEGER DEFAULT 0,
            homepage TEXT,
            last_commit_at TIMESTAMP,
            featured BOOLEAN DEFAULT FALSE,
            synced_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pv_visitor ON page_views(visitor_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pv_created ON page_views(created_at);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_click_time ON click_logs(clicked_at);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_visitors_created ON visitors(created_at);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_slug ON posts(slug);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);")

    conn.commit()

    # Seed blog posts if empty
    cur.execute("SELECT COUNT(*) FROM posts")
    if cur.fetchone()[0] == 0:
        _seed_blog_posts(cur)
        conn.commit()

    # Sync GitHub projects if empty
    cur.execute("SELECT COUNT(*) FROM projects")
    if cur.fetchone()[0] == 0:
        conn.commit()
        cur.close()
        conn.close()
        _seed_github_projects()
        return

    cur.close()
    conn.close()


def _seed_blog_posts(cur):
    tags = ["Azure", "AI", "Python", "Troubleshooting", "DevOps",
            "Machine Learning", "Cloud", "SQL", "Networking", "Career"]
    for t in tags:
        cur.execute("INSERT INTO tags (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (t,))

    posts = [
        {
            "slug": "azure-openai-service-troubleshooting-guide",
            "title": "Azure OpenAI Service: Common Issues & How I Solve Them",
            "summary": "A deep-dive into the most frequent support cases I handle for Azure OpenAI — from quota limits to content filtering.",
            "content": r"""As a Technical Support Engineer at Microsoft specializing in AI, I work with Azure OpenAI Service daily. Here are the top issues and my approach.

## 1. Quota & Rate Limiting (HTTP 429)

The most common issue. Customers hit Tokens-Per-Minute (TPM) or Requests-Per-Minute (RPM) limits.

**Diagnosis SQL I run:**

```sql
SELECT model_name, deployment_name,
       SUM(tokens_used) as total_tokens,
       COUNT(*) as request_count,
       DATE_TRUNC('minute', created_at) as minute
FROM api_logs
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY model_name, deployment_name, minute
ORDER BY total_tokens DESC;
```

**Resolution:**
- Check current quota vs usage in Azure Portal
- Recommend Provisioned Throughput Units (PTU) for predictable workloads
- Implement exponential backoff with jitter
- Use multiple deployments with load balancing

## 2. Content Filter Triggers (HTTP 400)

Azure OpenAI has built-in content filtering. Sometimes legitimate requests get blocked.

**Debugging approach:**
1. Check `content_filter_result` in the response body
2. Identify which category triggered: hate, sexual, violence, self-harm
3. Review the severity level
4. If false positive: recommend applying for modified content filtering

```python
response = client.chat.completions.create(...)
for choice in response.choices:
    if choice.content_filter_results:
        for category, result in choice.content_filter_results.items():
            if result.filtered:
                print(f"Blocked by: {category}, severity: {result.severity}")
```

## 3. Model Deployment Failures

**Checklist:**
- Verify the model is available in the selected region
- Check subscription-level quota for the specific model
- Ensure the API version matches the model capability
- For GPT-4 Turbo: verify `2024-02-15-preview` or later API version

## Key Takeaway

Support engineering is detective work with data. The better your monitoring SQL queries, the faster you resolve issues.""",
            "tags": ["Azure", "AI", "Troubleshooting"]
        },
        {
            "slug": "building-ai-support-diagnostic-tools-python",
            "title": "Building Internal Diagnostic Tools with Python for AI Support",
            "summary": "How I built Python automation tools to speed up Azure AI support — from log parsing to automated health checks.",
            "content": r"""One of the most rewarding parts of my role at Microsoft is building tools that help my team work faster.

## The Problem

Each support case involves:
1. Pulling customer resource configurations via Azure CLI
2. Analyzing API call logs for patterns
3. Checking service health across regions
4. Correlating timestamps across multiple systems

Manually: 30-45 minutes per case. After automation: 2 minutes.

## The Solution: Diagnostic Toolkit

### 1. Resource Health Checker

```python
import subprocess, json

def check_openai_resource(subscription_id, resource_group, account_name):
    cmd = [
        "az", "cognitiveservices", "account", "show",
        "--subscription", subscription_id,
        "--resource-group", resource_group,
        "--name", account_name, "--output", "json"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    resource = json.loads(result.stdout)

    issues = []
    net = resource.get("properties", {}).get("networkAcls", {})
    if net.get("defaultAction") == "Deny" and not net.get("virtualNetworkRules"):
        issues.append("Network set to Deny but no VNet rules configured")

    encryption = resource.get("properties", {}).get("encryption", {})
    if encryption.get("keySource") == "Microsoft.KeyVault":
        issues.append("CMK enabled - verify Key Vault access and key expiry")

    return {"name": account_name, "location": resource["location"],
            "sku": resource["sku"]["name"], "issues": issues}
```

### 2. Log Pattern Analyzer

```python
from collections import Counter

def analyze_error_patterns(logs):
    errors = [l for l in logs if l["status_code"] >= 400]
    return {
        "total_errors": len(errors),
        "error_distribution": Counter(l["status_code"] for l in errors),
        "top_models": Counter(l["model"] for l in errors).most_common(5)
    }
```

## Impact
- Case resolution time: **45 min -> 2 min**
- Now used by 12 engineers across the AI support pod
- Built a Flask web UI on top (similar to this portfolio!)""",
            "tags": ["Python", "AI", "Azure", "DevOps"]
        },
        {
            "slug": "postgresql-query-optimization-real-cases",
            "title": "PostgreSQL Query Optimization: Real Cases from Production",
            "summary": "Five real-world PostgreSQL performance issues — with before/after queries and index strategies.",
            "content": r"""Working in Azure support, I've seen PostgreSQL performance issues from simple missing indexes to complex query plan disasters.

## Case 1: The 30-Second Dashboard Query

**Original (slow):**
```sql
SELECT u.name, COUNT(o.id) as order_count, SUM(o.total) as revenue
FROM users u LEFT JOIN orders o ON u.id = o.user_id
WHERE o.created_at BETWEEN '2025-01-01' AND '2025-12-31'
GROUP BY u.name ORDER BY revenue DESC LIMIT 50;
```

**Fix:**
```sql
CREATE INDEX idx_orders_date_user ON orders(created_at, user_id) INCLUDE (total);

WITH recent AS (
    SELECT user_id, COUNT(*) as cnt, SUM(total) as rev
    FROM orders WHERE created_at BETWEEN '2025-01-01' AND '2025-12-31'
    GROUP BY user_id ORDER BY rev DESC LIMIT 50
)
SELECT u.name, r.cnt, r.rev FROM recent r JOIN users u ON r.user_id = u.id;
```
**Result:** 30s -> 45ms (667x faster).

## Case 2: N+1 Query Pattern

```python
# BAD: N+1 queries
for user in User.query.all():       # 1 query
    orders = user.orders.all()       # N queries!

# GOOD: Single query with JOIN
db.session.query(User, func.count(Order.id))\
    .outerjoin(Order).group_by(User.id).all()
```

## Case 3: Trigram Index for LIKE Queries

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_name_trgm ON products USING GIN(name gin_trgm_ops);
-- Now 'WHERE name LIKE '%widget%'' uses the index!
```

## Case 4: Window Functions vs Subqueries

```sql
-- SLOW: correlated subquery
SELECT * FROM orders o WHERE o.created_at = (
    SELECT MAX(created_at) FROM orders WHERE user_id = o.user_id);

-- FAST: window function
SELECT * FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC) as rn
    FROM orders
) ranked WHERE rn = 1;
```

## Case 5: Dead Tuples & VACUUM

```sql
SELECT relname, n_live_tup, n_dead_tup,
       ROUND(100.0 * n_dead_tup / GREATEST(n_live_tup + n_dead_tup, 1), 1) as dead_pct
FROM pg_stat_user_tables WHERE n_dead_tup > 10000 ORDER BY dead_pct DESC;

ALTER TABLE orders SET (autovacuum_vacuum_scale_factor = 0.05);
VACUUM ANALYZE orders;
```""",
            "tags": ["SQL", "Azure", "Troubleshooting"]
        },
        {
            "slug": "azure-networking-private-endpoints-explained",
            "title": "Azure Private Endpoints & VNet: What I Wish I Knew Day One",
            "summary": "A practical guide to Azure networking — Private Endpoints, VNet Integration, NSGs — through real scenarios.",
            "content": r"""When I started at Microsoft, Azure networking was the most confusing part. Here's the mental model I wish someone gave me.

## The Core Concept: Two Directions

- **VNet Integration** = Controls where YOUR APP can GO OUT to
- **Private Endpoint** = Creates a private mailbox for a service INSIDE your VNet

```
Internet --> [Web App] --VNet Integration--> [VNet]
                                               |
                                   +-----------+-----------+
                                   |           |           |
                              [PostgreSQL] [Redis]    [Storage]
                              (Private EP) (Private EP)
```

## How This Portfolio Site Works

**Inbound:** User -> Azure Load Balancer -> App Service (HTTPS)
**Outbound:** Flask -> VNet Integration -> Private Endpoint -> PostgreSQL/Redis
**Security:** Database ONLY accepts VNet connections - public internet blocked.

## DNS with Private Endpoints

```bash
# Inside VNet (your app):
nslookup mydb.postgres.database.azure.com -> 10.0.1.4 (private IP)

# Your laptop:
nslookup mydb.postgres.database.azure.com -> 52.x.x.x (public, refused)
```

## NSG Rules = Firewall

```
Subnet: db-subnet
  Allow inbound 5432 from webapp-subnet  [checkmark]
  Deny all other inbound                 [x]
```

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| VNet Integration not enabled | App Service -> Networking -> Enable |
| Private DNS Zone not linked | Link privatelink.* zone to VNet |
| Wrong subnet delegation | App Service needs its own subnet |

## Rule of Thumb
- Always Private Endpoints for databases
- Always VNet Integration for App Service
- Never expose DB ports to public internet""",
            "tags": ["Azure", "Networking", "Cloud"]
        },
        {
            "slug": "my-journey-from-ai-support-to-building-tools",
            "title": "From Answering Tickets to Building Tools: My Growth at Microsoft",
            "summary": "How I went from solving individual cases to building automation that helps the entire team.",
            "content": r"""When I joined Microsoft as an AI Support Engineer, I thought the job was just answering customer questions. Two years in, it's so much more.

## Phase 1: Learning Curve (Months 1-3)

Every case felt overwhelming. Azure has hundreds of services. My routine:
1. Pick up a case
2. Spend 30 min understanding the customer's architecture
3. Google the error (yes, even at Microsoft)
4. Ask senior engineers
5. Resolve

## Phase 2: Pattern Recognition (Months 4-8)

After 200+ cases, patterns emerged:
- 40% of cases = same 5 issues
- Most networking problems = Private Endpoint DNS
- Quota issues spike Monday mornings (batch jobs)

```python
CASE_PATTERNS = {
    "429_rate_limit": {"frequency": "35%", "avg_resolution_min": 15},
    "networking_private_endpoint": {"frequency": "20%", "avg_resolution_min": 45},
    "content_filter": {"frequency": "15%", "avg_resolution_min": 20},
}
```

## Phase 3: Automation (Months 9-14)

- **Case Pre-Analyzer:** Pulls resource config, highlights issues automatically
- **Response Template Generator:** Personalized responses with customer's resource names
- **Health Dashboard:** Flask + PostgreSQL monitoring failure patterns

```sql
WITH weekly AS (
    SELECT DATE_TRUNC('week', resolved_at) as week, category,
           COUNT(*) as cases, AVG(EXTRACT(EPOCH FROM (resolved_at - created_at))/3600) as avg_hrs
    FROM support_cases WHERE resolved_at > NOW() - INTERVAL '3 months'
    GROUP BY week, category
)
SELECT week, category, cases,
       ROUND(avg_hrs::numeric, 1) as hrs,
       ROUND(avg_hrs - LAG(avg_hrs) OVER (PARTITION BY category ORDER BY week), 1) as delta
FROM weekly ORDER BY week DESC;
```

## Phase 4: Sharing (Months 15+)

- Internal wiki: 200+ articles
- Weekly "Debugging Deep Dive" sessions
- Mentoring new hires

## What I Learned

1. **Document everything** - Notes become tools, tools become reputation
2. **Automate the boring parts** - Frees your brain for interesting problems
3. **Share generously** - Teaching solidifies knowledge
4. **Build in public** - This portfolio is part of that
5. **Stay curious** - Still learn something new every week""",
            "tags": ["Career", "AI", "Azure"]
        },
    ]

    for post in posts:
        cur.execute(
            """INSERT INTO posts (slug, title, summary, content, status, published_at)
               VALUES (%s, %s, %s, %s, 'published', NOW()) ON CONFLICT (slug) DO NOTHING RETURNING id""",
            (post["slug"], post["title"], post["summary"], post["content"])
        )
        row = cur.fetchone()
        if row:
            post_id = row[0]
            for tag_name in post.get("tags", []):
                cur.execute("INSERT INTO tags (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (tag_name,))
                cur.execute("SELECT id FROM tags WHERE name = %s", (tag_name,))
                tag_id = cur.fetchone()[0]
                cur.execute("INSERT INTO post_tags (post_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                            (post_id, tag_id))


def _seed_github_projects():
    """Sync GitHub repos into projects table on first startup."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    try:
        resp = http_requests.get(
            f"https://api.github.com/users/{GITHUB_USERNAME}/repos",
            headers=headers, params={"sort": "updated", "per_page": 30}, timeout=15
        )
        resp.raise_for_status()
        repos = resp.json()
    except Exception as e:
        print(f"GitHub sync on startup failed: {e}")
        return

    conn = get_db()
    cur = conn.cursor()
    for repo in repos:
        if repo.get("fork"):
            continue
        cur.execute("""
            INSERT INTO projects (github_repo, name, description, language, stars, forks,
                                  open_issues, homepage, last_commit_at, synced_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (github_repo) DO UPDATE SET
                name=EXCLUDED.name, description=EXCLUDED.description, language=EXCLUDED.language,
                stars=EXCLUDED.stars, forks=EXCLUDED.forks, open_issues=EXCLUDED.open_issues,
                homepage=EXCLUDED.homepage, last_commit_at=EXCLUDED.last_commit_at, synced_at=NOW()
        """, (repo["full_name"], repo["name"], repo.get("description"),
              repo.get("language"), repo.get("stargazers_count", 0), repo.get("forks_count", 0),
              repo.get("open_issues_count", 0), repo.get("homepage"), repo.get("pushed_at")))
    conn.commit()
    cur.close()
    conn.close()
    print(f"GitHub projects seeded: {len([r for r in repos if not r.get('fork')])} repos")


try:
    init_db()
except Exception as e:
    print(f"DB init warning (will retry on first request): {e}")

# ── Helpers ────────────────────────────────────────────────
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

def is_valid_email(email):
    if not EMAIL_RE.match(email):
        return False, "Invalid email format."
    domain = email.split("@")[1].lower()
    if domain in BLOCKED_DOMAINS:
        return False, "Disposable or blocked email domain."
    return True, "OK"

def send_notification(visitor_name, visitor_email, message_text):
    try:
        body = (
            f"New message from your portfolio site!\n\n"
            f"From: {visitor_name} <{visitor_email}>\n"
            f"Time: {datetime.utcnow().isoformat()}\n\n"
            f"Message:\n{message_text}"
        )
        msg = MIMEText(body)
        msg["Subject"] = f"Portfolio Contact: {visitor_name}"
        msg["From"] = SMTP_USER
        msg["To"] = OWNER_EMAIL
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [OWNER_EMAIL], msg.as_string())
        return True
    except Exception:
        return False

def require_verified(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("verified"):
            return jsonify({"error": "Not verified"}), 403
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"error": "Admin login required"}), 401
        return f(*args, **kwargs)
    return decorated

def hash_ip(ip):
    return hashlib.sha256((ip or "unknown").encode()).hexdigest()[:16]

# ── Static file routes ─────────────────────────────────────
@app.route("/")
def index():
    if session.get("verified"):
        return send_from_directory("static", "index.html")
    return send_from_directory("static", "verify.html")

@app.route("/blog")
def blog_page():
    return send_from_directory("static", "blog.html")

@app.route("/blog/<slug>")
def blog_post_page(slug):
    return send_from_directory("static", "post.html")

@app.route("/projects")
def projects_page():
    return send_from_directory("static", "projects.html")

@app.route("/admin")
def admin_page():
    return send_from_directory("static", "admin.html")

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)

# ── Visitor Verification ───────────────────────────────────
@app.route("/api/verify", methods=["POST"])
def verify_visitor():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()

    if not name or not email:
        return jsonify({"error": "Name and email are required."}), 400
    valid, reason = is_valid_email(email)
    if not valid:
        return jsonify({"error": reason}), 400

    token = secrets.token_urlsafe(32)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO visitors (name, email, verified, token) VALUES (%s, %s, 1, %s) RETURNING id",
        (name, email, token),
    )
    visitor_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()

    session["verified"] = True
    session["visitor_id"] = visitor_id
    session["visitor_name"] = name
    session["visitor_email"] = email
    return jsonify({"success": True, "redirect": "/"})

# ── Page View Tracking ─────────────────────────────────────
@app.route("/api/pageview", methods=["POST"])
def record_pageview():
    data = request.get_json() or {}
    page = (data.get("page") or "/").strip()
    referrer = (data.get("referrer") or "").strip()
    screen_width = data.get("screen_width")
    duration = data.get("duration_sec", 0)
    visitor_id = session.get("visitor_id")

    ip = hash_ip(request.remote_addr)
    ua = (request.headers.get("User-Agent") or "")[:500]

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO page_views (visitor_id, page, referrer, user_agent, ip_hash, duration_sec, screen_width)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (visitor_id, page, referrer, ua, ip, duration, screen_width),
    )

    sess_token = session.get("sess_token")
    if sess_token:
        cur.execute(
            "UPDATE visitor_sessions SET page_count = page_count + 1, ended_at = NOW() WHERE session_token = %s",
            (sess_token,)
        )
    elif visitor_id:
        sess_token = secrets.token_urlsafe(16)
        session["sess_token"] = sess_token
        cur.execute(
            "INSERT INTO visitor_sessions (visitor_id, session_token, page_count) VALUES (%s, %s, 1)",
            (visitor_id, sess_token)
        )

    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})

# ── Click Tracking ─────────────────────────────────────────
@app.route("/api/track", methods=["POST"])
@require_verified
def track_click():
    data = request.get_json()
    element = (data.get("element") or "").strip()
    page = (data.get("page") or "").strip()
    if not element:
        return jsonify({"error": "element is required"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO click_logs (visitor_id, element, page) VALUES (%s, %s, %s)",
        (session.get("visitor_id"), element, page),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})

# ── Contact Form ───────────────────────────────────────────
@app.route("/api/contact", methods=["POST"])
@require_verified
def contact():
    data = request.get_json()
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Message is required."}), 400

    visitor_id = session.get("visitor_id")
    name = session.get("visitor_name", "Anonymous")
    email = session.get("visitor_email", "unknown")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (visitor_id, name, email, message) VALUES (%s, %s, %s, %s)",
        (visitor_id, name, email, message),
    )
    conn.commit()
    cur.close()
    conn.close()

    cache_delete("stats:*")
    email_sent = send_notification(name, email, message)
    return jsonify({"success": True, "email_sent": email_sent,
                    "note": "Message saved!" + (" Email sent to owner." if email_sent else "")})

# ── Blog API ───────────────────────────────────────────────
@app.route("/api/posts")
def api_list_posts():
    tag = request.args.get("tag", "").strip()
    page_num = max(1, int(request.args.get("page", "1")))
    per_page = min(20, int(request.args.get("per_page", "10")))
    offset = (page_num - 1) * per_page

    cache_key = f"posts:list:{tag}:{page_num}:{per_page}"
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if tag:
        cur.execute("""
            SELECT p.id, p.slug, p.title, p.summary, p.views, p.published_at::text as published_at
            FROM posts p JOIN post_tags pt ON p.id = pt.post_id JOIN tags t ON pt.tag_id = t.id
            WHERE p.status = 'published' AND t.name = %s
            ORDER BY p.published_at DESC LIMIT %s OFFSET %s
        """, (tag, per_page, offset))
    else:
        cur.execute("""
            SELECT id, slug, title, summary, views, published_at::text as published_at
            FROM posts WHERE status = 'published'
            ORDER BY published_at DESC LIMIT %s OFFSET %s
        """, (per_page, offset))

    posts = cur.fetchall()
    for post in posts:
        cur.execute("""
            SELECT t.name FROM tags t JOIN post_tags pt ON t.id = pt.tag_id WHERE pt.post_id = %s
        """, (post["id"],))
        post["tags"] = [r["name"] for r in cur.fetchall()]

    if tag:
        cur.execute("""SELECT COUNT(*) as c FROM posts p JOIN post_tags pt ON p.id = pt.post_id
                       JOIN tags t ON pt.tag_id = t.id WHERE p.status='published' AND t.name=%s""", (tag,))
    else:
        cur.execute("SELECT COUNT(*) as c FROM posts WHERE status = 'published'")
    total = cur.fetchone()["c"]

    cur.close()
    conn.close()

    result = {"posts": posts, "total": total, "page": page_num, "per_page": per_page}
    cache_set(cache_key, result, ttl=120)
    return jsonify(result)

@app.route("/api/posts/<slug>")
def api_get_post(slug):
    cache_key = f"post:{slug}"
    cached = cache_get(cache_key)
    if cached:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("UPDATE posts SET views = views + 1 WHERE slug = %s", (slug,))
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass
        return jsonify(cached)

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT id, slug, title, summary, content, views, status,
               published_at::text as published_at, updated_at::text as updated_at
        FROM posts WHERE slug = %s
    """, (slug,))
    post = cur.fetchone()
    if not post:
        cur.close()
        conn.close()
        return jsonify({"error": "Post not found"}), 404

    cur.execute("SELECT t.name FROM tags t JOIN post_tags pt ON t.id = pt.tag_id WHERE pt.post_id = %s",
                (post["id"],))
    post["tags"] = [r["name"] for r in cur.fetchall()]
    cur.execute("UPDATE posts SET views = views + 1 WHERE slug = %s", (slug,))
    conn.commit()
    cur.close()
    conn.close()

    cache_set(cache_key, post, ttl=300)
    return jsonify(post)

@app.route("/api/tags")
def api_list_tags():
    cached = cache_get("tags:all")
    if cached:
        return jsonify(cached)
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT t.name, COUNT(pt.post_id) as post_count FROM tags t
        LEFT JOIN post_tags pt ON t.id = pt.tag_id
        LEFT JOIN posts p ON pt.post_id = p.id AND p.status = 'published'
        GROUP BY t.name HAVING COUNT(pt.post_id) > 0
        ORDER BY post_count DESC
    """)
    tags = cur.fetchall()
    cur.close()
    conn.close()
    cache_set("tags:all", tags, ttl=300)
    return jsonify(tags)

# ── Projects / GitHub API ──────────────────────────────────
@app.route("/api/projects")
def api_list_projects():
    cached = cache_get("projects:all")
    if cached:
        return jsonify(cached)
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT id, github_repo, name, description, language, stars, forks,
               open_issues, homepage, featured,
               last_commit_at::text as last_commit_at, synced_at::text as synced_at
        FROM projects ORDER BY featured DESC, stars DESC, last_commit_at DESC NULLS LAST
    """)
    projects = cur.fetchall()
    cur.close()
    conn.close()
    cache_set("projects:all", projects, ttl=300)
    return jsonify(projects)

@app.route("/api/projects/sync", methods=["POST"])
@require_admin
def sync_github_projects():
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    try:
        resp = http_requests.get(
            f"https://api.github.com/users/{GITHUB_USERNAME}/repos",
            headers=headers, params={"sort": "updated", "per_page": 30}, timeout=15
        )
        resp.raise_for_status()
        repos = resp.json()
    except Exception as e:
        return jsonify({"error": f"GitHub API failed: {str(e)}"}), 502

    conn = get_db()
    cur = conn.cursor()
    synced = 0
    for repo in repos:
        if repo.get("fork"):
            continue
        cur.execute("""
            INSERT INTO projects (github_repo, name, description, language, stars, forks,
                                  open_issues, homepage, last_commit_at, synced_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (github_repo) DO UPDATE SET
                name=EXCLUDED.name, description=EXCLUDED.description, language=EXCLUDED.language,
                stars=EXCLUDED.stars, forks=EXCLUDED.forks, open_issues=EXCLUDED.open_issues,
                homepage=EXCLUDED.homepage, last_commit_at=EXCLUDED.last_commit_at, synced_at=NOW()
        """, (repo["full_name"], repo["name"], repo.get("description"),
              repo.get("language"), repo.get("stargazers_count", 0), repo.get("forks_count", 0),
              repo.get("open_issues_count", 0), repo.get("homepage"), repo.get("pushed_at")))
        synced += 1
    conn.commit()
    cur.close()
    conn.close()
    cache_delete("projects:*")
    return jsonify({"success": True, "synced": synced})

# ── Admin Login ────────────────────────────────────────────
@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json()
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"error": "Credentials required"}), 400
    if username != ADMIN_USER:
        return jsonify({"error": "Invalid credentials"}), 401

    if ADMIN_PASS_HASH:
        if not bcrypt.checkpw(password.encode(), ADMIN_PASS_HASH.encode()):
            return jsonify({"error": "Invalid credentials"}), 401
    else:
        admin_pass = os.environ.get("ADMIN_PASS", "admin123")
        if password != admin_pass:
            return jsonify({"error": "Invalid credentials"}), 401

    session["is_admin"] = True
    return jsonify({"success": True})

@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    return jsonify({"success": True})

# ── Admin Analytics Dashboard API ──────────────────────────
@app.route("/api/admin/stats")
@require_admin
def admin_stats():
    cached = cache_get("stats:overview")
    if cached:
        return jsonify(cached)

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT COUNT(*) as c FROM visitors")
    visitors = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM click_logs")
    clicks = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM messages")
    messages = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM page_views")
    pageviews = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM posts WHERE status = 'published'")
    post_count = cur.fetchone()["c"]

    cur.execute("""
        SELECT DATE(created_at)::text as day, COUNT(*) as count FROM visitors
        WHERE created_at > NOW() - INTERVAL '30 days' GROUP BY DATE(created_at) ORDER BY day
    """)
    visitors_per_day = cur.fetchall()

    cur.execute("""
        SELECT DATE(created_at)::text as day, COUNT(*) as count FROM page_views
        WHERE created_at > NOW() - INTERVAL '30 days' GROUP BY DATE(created_at) ORDER BY day
    """)
    pageviews_per_day = cur.fetchall()

    cur.execute("""
        SELECT element, COUNT(*) as clicks FROM click_logs GROUP BY element ORDER BY clicks DESC LIMIT 15
    """)
    top_clicks = cur.fetchall()

    cur.execute("""
        SELECT page, COUNT(*) as views, COALESCE(AVG(duration_sec)::int, 0) as avg_duration
        FROM page_views GROUP BY page ORDER BY views DESC LIMIT 10
    """)
    top_pages = cur.fetchall()

    cur.execute("""
        SELECT SPLIT_PART(email, '@', 2) as domain, COUNT(*) as count
        FROM visitors GROUP BY domain ORDER BY count DESC LIMIT 15
    """)
    email_domains = cur.fetchall()

    cur.execute("""
        SELECT CASE WHEN screen_width IS NULL THEN 'Unknown'
                    WHEN screen_width < 768 THEN 'Mobile'
                    WHEN screen_width < 1024 THEN 'Tablet'
                    ELSE 'Desktop' END as device, COUNT(*) as count
        FROM page_views GROUP BY device ORDER BY count DESC
    """)
    devices = cur.fetchall()

    cur.execute("""
        SELECT id, name, email, message, sent_at::text as sent_at
        FROM messages ORDER BY sent_at DESC LIMIT 10
    """)
    recent_messages = cur.fetchall()

    cur.execute("""
        SELECT slug, title, views, published_at::text as published_at
        FROM posts WHERE status = 'published' ORDER BY views DESC LIMIT 10
    """)
    top_posts = cur.fetchall()

    cur.close()
    conn.close()

    result = {
        "visitors": visitors, "clicks": clicks, "messages": messages,
        "pageviews": pageviews, "post_count": post_count,
        "visitors_per_day": visitors_per_day, "pageviews_per_day": pageviews_per_day,
        "top_clicks": top_clicks, "top_pages": top_pages,
        "email_domains": email_domains, "devices": devices,
        "recent_messages": recent_messages, "top_posts": top_posts,
    }
    cache_set("stats:overview", result, ttl=60)
    return jsonify(result)

# ── Admin: Visitors with Pagination ────────────────────────
@app.route("/api/admin/visitors")
@require_admin
def admin_visitors():
    page_num = max(1, int(request.args.get("page", "1")))
    per_page = min(50, int(request.args.get("per_page", "20")))
    domain_filter = request.args.get("domain", "").strip()
    offset = (page_num - 1) * per_page

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if domain_filter:
        cur.execute("""SELECT id, name, email, created_at::text as created_at FROM visitors
                       WHERE email LIKE %s ORDER BY created_at DESC LIMIT %s OFFSET %s""",
                    (f"%@{domain_filter}", per_page, offset))
    else:
        cur.execute("""SELECT id, name, email, created_at::text as created_at FROM visitors
                       ORDER BY created_at DESC LIMIT %s OFFSET %s""", (per_page, offset))
    visitors = cur.fetchall()

    if domain_filter:
        cur.execute("SELECT COUNT(*) as c FROM visitors WHERE email LIKE %s", (f"%@{domain_filter}",))
    else:
        cur.execute("SELECT COUNT(*) as c FROM visitors")
    total = cur.fetchone()["c"]

    cur.close()
    conn.close()
    return jsonify({"visitors": visitors, "total": total, "page": page_num, "per_page": per_page})

# ── Admin: Export CSV ──────────────────────────────────────
@app.route("/api/admin/export/<table>")
@require_admin
def admin_export(table):
    allowed = {"visitors", "click_logs", "messages", "page_views"}
    if table not in allowed:
        return jsonify({"error": "Invalid table"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT 5000")  # table is from allowlist
    rows = cur.fetchall()
    colnames = [desc[0] for desc in cur.description]
    cur.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(colnames)
    for row in rows:
        writer.writerow([str(v) if v is not None else "" for v in row])

    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f"attachment; filename={table}_export.csv"
    return response

# ── Admin: Retention Analysis ──────────────────────────────
@app.route("/api/admin/retention")
@require_admin
def admin_retention():
    cached = cache_get("stats:retention")
    if cached:
        return jsonify(cached)

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        WITH first_visit AS (
            SELECT visitor_id, DATE(MIN(created_at)) as first_day
            FROM page_views WHERE visitor_id IS NOT NULL GROUP BY visitor_id
        ),
        daily_activity AS (
            SELECT DISTINCT visitor_id, DATE(created_at) as active_day
            FROM page_views WHERE visitor_id IS NOT NULL
        )
        SELECT fv.first_day::text as cohort_date, COUNT(DISTINCT fv.visitor_id) as cohort_size,
               COUNT(DISTINCT CASE WHEN da.active_day = fv.first_day THEN da.visitor_id END) as day_0,
               COUNT(DISTINCT CASE WHEN da.active_day = fv.first_day + 1 THEN da.visitor_id END) as day_1,
               COUNT(DISTINCT CASE WHEN da.active_day = fv.first_day + 7 THEN da.visitor_id END) as day_7,
               COUNT(DISTINCT CASE WHEN da.active_day = fv.first_day + 30 THEN da.visitor_id END) as day_30
        FROM first_visit fv LEFT JOIN daily_activity da ON fv.visitor_id = da.visitor_id
        WHERE fv.first_day > NOW() - INTERVAL '60 days'
        GROUP BY fv.first_day ORDER BY fv.first_day DESC LIMIT 30
    """)
    retention = cur.fetchall()
    cur.close()
    conn.close()
    cache_set("stats:retention", retention, ttl=300)
    return jsonify(retention)

# ── Run ────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000)
