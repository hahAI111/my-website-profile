# How to Deploy & Run the Website — From Code to Live Site

This guide explains how `app.py` + HTML files become a live website that anyone can visit. Covers running locally, deploying to cloud platforms, and understanding the full deployment pipeline.

---

## Table of Contents

- [The Core Concept: How Code Becomes a Website](#the-core-concept-how-code-becomes-a-website)
- [What You Need to Run This Website](#what-you-need-to-run-this-website)
- [Method 1: Run Locally (Your Own Computer)](#method-1-run-locally-your-own-computer)
  - [Option A: With Docker (Easiest)](#option-a-with-docker-easiest)
  - [Option B: Install PostgreSQL Manually](#option-b-install-postgresql-manually)
  - [Option C: Minimal (No Database)](#option-c-minimal-no-database)
- [Method 2: Deploy to Railway (Recommended for Free Hosting)](#method-2-deploy-to-railway-recommended-for-free-hosting)
- [Method 3: Deploy to Render](#method-3-deploy-to-render)
- [Method 4: Deploy to Personal Azure Account](#method-4-deploy-to-personal-azure-account)
- [Method 5: Deploy to Any Linux VPS](#method-5-deploy-to-any-linux-vps)
- [How the Current Azure Deployment Works](#how-the-current-azure-deployment-works)
  - [The Full Pipeline: git push → Live Website](#the-full-pipeline-git-push--live-website)
  - [What GitHub Actions Does](#what-github-actions-does)
  - [What Azure App Service Does](#what-azure-app-service-does)
- [Platform Comparison](#platform-comparison)
- [All Deployment Methods at a Glance](#all-deployment-methods-at-a-glance)
- [Environment Variables Reference](#environment-variables-reference)
- [FAQ](#faq)

---

## The Core Concept: How Code Becomes a Website

```
Your code (app.py + static/HTML/CSS/JS)
        │
        ▼
A computer runs the Flask server
  (python app.py  or  gunicorn app:app)
        │
        ▼
Server listens on a port (e.g., port 5000 or 8000)
        │
        ▼
User's browser sends HTTP request to that computer's address
        │
        ▼
Flask @app.route receives the request
        │
        ├── Page request? → Return HTML file from static/ folder
        └── API request?  → Query PostgreSQL → Return JSON data
        │
        ▼
Browser renders the page → User sees the website
```

**In one sentence:** A computer runs `app.py` 24/7, and anyone who knows its address can visit the website through a browser.

**The difference between "local" and "deployed":**

| | Local | Cloud Deployed |
|---|---|---|
| Who runs `app.py`? | Your laptop | A server in a data center |
| Address | `localhost:5000` | `yourapp.azurewebsites.net` |
| Who can access? | Only you | Anyone on the internet |
| Uptime | Only when your computer is on | 24/7 |

**Cloud deployment simply means:** Someone else's computer runs your code 24/7 and gives it a public URL.

---

## What You Need to Run This Website

| Component | Required? | Purpose |
|-----------|-----------|---------|
| **Python 3.9+** | Yes | Runs Flask backend |
| **Flask + dependencies** | Yes | `pip install -r requirements.txt` |
| **PostgreSQL** | Yes | Stores all data (visitors, posts, etc.) |
| **Redis** | No (optional) | Caching — site works without it, just slower |
| **Gmail account with App Password** | No (optional) | Email notifications for contact form |
| **GitHub Token** | No (optional) | Higher API rate limit for project sync |

**Absolute minimum:** Python + PostgreSQL + the code. That's it.

---

## Method 1: Run Locally (Your Own Computer)

### Option A: With Docker (Easiest)

If you have Docker Desktop installed:

```powershell
# 1. Start PostgreSQL in a container
docker run -d --name portfolio-db -p 5432:5432 `
  -e POSTGRES_DB=portfoliodb `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=postgres `
  postgres:15

# 2. (Optional) Start Redis in a container
docker run -d --name portfolio-redis -p 6379:6379 redis:7

# 3. Clone the code
git clone https://github.com/hahAI111/aimeewebpage.git
cd aimeewebpage

# 4. Create virtual environment and install dependencies
python -m venv venv
.\venv\Scripts\Activate
pip install -r requirements.txt

# 5. Set environment variables
$env:AZURE_POSTGRESQL_CONNECTIONSTRING = "host=localhost dbname=portfoliodb user=postgres password=postgres"
$env:AZURE_REDIS_CONNECTIONSTRING = "redis://localhost:6379/0"
$env:SECRET_KEY = "any-random-string-for-local-dev"
$env:ADMIN_PASS = "admin123"

# 6. Run!
python app.py
```

Open browser → `http://localhost:5000` → Website is live!

- Flask auto-creates all 9 tables on first startup
- Blog posts are auto-seeded (5 posts)
- GitHub projects are auto-synced
- Admin login: username `admin`, password `admin123`

### Option B: Install PostgreSQL Manually

1. Download PostgreSQL from [postgresql.org/download](https://www.postgresql.org/download/)
2. Install with default settings (remember the password you set)
3. Create a database:
   ```sql
   CREATE DATABASE portfoliodb;
   ```
4. Follow steps 3-6 from Option A above, using your local PostgreSQL credentials

### Option C: Minimal (No Database)

If you just want to see the HTML/CSS:
```powershell
# Install Python's built-in HTTP server
cd aimeewebpage/static
python -m http.server 5000
```
This shows the static pages but no backend functionality (no login, no data, no API).

**Limitation of all local methods:** Only you can see the website. It stops when you close the terminal. To make it public, you need cloud deployment.

---

## Method 2: Deploy to Railway (Recommended for Free Hosting)

Railway is the easiest way to get Flask + PostgreSQL + Redis for free.

### Step 1: Sign Up
- Go to [railway.app](https://railway.app)
- Click **Login** → Sign in with your GitHub account

### Step 2: Create Project from GitHub
1. Click **New Project**
2. Select **Deploy from GitHub Repo**
3. Find and select `hahAI111/aimeewebpage`
4. Railway auto-detects Python → installs `requirements.txt` → starts the app

### Step 3: Add PostgreSQL
1. In your project dashboard, click **+ New**
2. Select **Database → PostgreSQL**
3. Railway creates a PostgreSQL instance instantly
4. Connection URL is auto-generated

### Step 4: Add Redis (Optional)
1. Click **+ New → Database → Redis**
2. Connection URL is auto-generated

### Step 5: Configure Environment Variables
Go to your web service → **Variables** tab → Add these:

```
# Link database URLs (Railway variable references)
AZURE_POSTGRESQL_CONNECTIONSTRING=${{Postgres.DATABASE_URL}}
AZURE_REDIS_CONNECTIONSTRING=${{Redis.REDIS_URL}}

# App configuration
SECRET_KEY=generate-a-long-random-string
ADMIN_USER=admin
ADMIN_PASS_HASH=your-bcrypt-hash
# (or ADMIN_PASS=your-plain-password)

# Email (optional)
OWNER_EMAIL=your@email.com
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-gmail@gmail.com
SMTP_PASS=your-app-password

# GitHub sync (optional)
GITHUB_USERNAME=hahAI111
GITHUB_TOKEN=your-token
```

### Step 6: Set Start Command
Go to **Settings → Start Command**:
```bash
gunicorn --bind=0.0.0.0:$PORT --timeout 600 app:app
```

### Step 7: Import Data (if you have a backup)
Get the PostgreSQL connection URL from Railway's Variables tab:
```bash
psql "postgresql://user:pass@host:port/railway" < backup.sql
```

### Step 8: Visit Your Site!
Railway provides a URL like `aimeewebpage-production.up.railway.app`.

**Auto-deploy is built in:** Every `git push` to `main` automatically redeploys. No GitHub Actions configuration needed.

---

## Method 3: Deploy to Render

### Step 1: Sign Up
- Go to [render.com](https://render.com)
- Sign in with GitHub

### Step 2: Create Web Service
1. Click **New → Web Service**
2. Connect your GitHub repo `hahAI111/aimeewebpage`
3. Configure:
   - **Name:** aimeewebpage
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn --bind=0.0.0.0:$PORT --timeout 600 app:app`

### Step 3: Create PostgreSQL
1. Click **New → PostgreSQL**
2. Choose the Free plan (1GB)
3. Copy the **Internal Database URL**

### Step 4: Create Redis (Optional)
1. Click **New → Redis**
2. Choose the Free plan (25MB)
3. Copy the **Internal Redis URL**

### Step 5: Set Environment Variables
In your Web Service → **Environment** tab:

```
AZURE_POSTGRESQL_CONNECTIONSTRING=postgresql://user:pass@host/dbname  (Internal URL from Step 3)
AZURE_REDIS_CONNECTIONSTRING=redis://red-xxxx:6379                    (Internal URL from Step 4)
SECRET_KEY=random-string
ADMIN_USER=admin
ADMIN_PASS_HASH=your-bcrypt-hash
OWNER_EMAIL=your@email.com
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-gmail@gmail.com
SMTP_PASS=your-app-password
GITHUB_USERNAME=hahAI111
```

### Step 6: Import Data & Go Live
```bash
psql "render-external-database-url" < backup.sql
```

Render gives you a URL like `aimeewebpage.onrender.com`.

---

## Method 4: Deploy to Personal Azure Account

If you want the **exact same setup** as the current company deployment:

### Step 1: Create Personal Azure Account
- Go to [azure.microsoft.com/free](https://azure.microsoft.com/en-us/free/)
- Sign up with personal email
- You get $200 credit + 12 months of free services

### Step 2: Create Resources (Same as Current)
```bash
# Create resource group
az group create --name my-portfolio --location canadacentral

# Create App Service plan + Web App
az appservice plan create --name my-plan --resource-group my-portfolio --sku B1 --is-linux
az webapp create --name my-portfolio-site --resource-group my-portfolio --plan my-plan --runtime "PYTHON:3.11"

# Create PostgreSQL
az postgres flexible-server create --name my-pg-server --resource-group my-portfolio --sku-name Standard_B1ms --tier Burstable --storage-size 32

# Create Redis (optional, saves ~$16/month if skipped)
az redis create --name my-redis --resource-group my-portfolio --sku Basic --vm-size C0
```

### Step 3: Import Data
```bash
psql "host=my-pg-server.postgres.database.azure.com dbname=postgres user=YOUR_USER sslmode=require" < backup.sql
```

### Step 4: Configure App Service
```bash
# Set environment variables
az webapp config appsettings set --name my-portfolio-site --resource-group my-portfolio --settings \
  AZURE_POSTGRESQL_CONNECTIONSTRING="host=my-pg-server.postgres.database.azure.com dbname=postgres user=YOUR_USER password=YOUR_PASS" \
  SECRET_KEY="your-secret" \
  ADMIN_USER="admin" \
  ADMIN_PASS_HASH="your-hash"

# Set startup command
az webapp config set --name my-portfolio-site --resource-group my-portfolio --startup-file "gunicorn --bind=0.0.0.0:8000 --timeout 600 app:app"
```

### Step 5: Set Up GitHub Actions
1. Download publish profile: Azure Portal → your App Service → **Get publish profile**
2. GitHub → your repo → **Settings → Secrets → Actions** → Add `AZUREAPPSERVICE_PUBLISHPROFILE` with the publish profile content
3. Update `.github/workflows/main_aimeelan.yml` → change `app-name` to your new app name

### Step 6: Push and Deploy
```bash
git push origin main
# GitHub Actions auto-builds and deploys to your personal Azure
```

---

## Method 5: Deploy to Any Linux VPS

For a $5/month VPS (DigitalOcean, Vultr, Linode):

```bash
# SSH into your server
ssh root@your-server-ip

# Install dependencies
apt update && apt install -y python3 python3-pip python3-venv postgresql redis-server nginx

# Set up PostgreSQL
sudo -u postgres createdb portfoliodb

# Clone and set up the app
git clone https://github.com/hahAI111/aimeewebpage.git
cd aimeewebpage
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Import data
psql -U postgres portfoliodb < backup.sql

# Set environment variables
export AZURE_POSTGRESQL_CONNECTIONSTRING="host=localhost dbname=portfoliodb user=postgres password=YOUR_PASS"
export AZURE_REDIS_CONNECTIONSTRING="redis://localhost:6379/0"
export SECRET_KEY="your-secret"
export ADMIN_USER="admin"
export ADMIN_PASS_HASH="your-hash"

# Run with gunicorn (production)
gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers 2 app:app

# (Optional) Set up nginx as reverse proxy + systemd for auto-start
# This keeps the app running 24/7 even after server reboot
```

---

## How the Current Azure Deployment Works

### The Full Pipeline: git push → Live Website

```
You: git push origin main
     │
     ▼
GitHub receives the code
     │
     ▼
GitHub Actions triggers (defined in .github/workflows/main_aimeelan.yml)
     │
     ├── Step 1: Set up Python 3.11
     ├── Step 2: Create virtual environment
     ├── Step 3: pip install -r requirements.txt
     ├── Step 4: Zip everything into a deployment package
     └── Step 5: Upload to Azure App Service using publish profile
     │
     ▼
Azure App Service receives the package
     │
     ├── Oryx build engine unpacks and prepares the app
     ├── Runs: gunicorn --bind=0.0.0.0:8000 --timeout 600 app:app
     └── Flask starts → connects to PostgreSQL → connects to Redis → ready
     │
     ▼
Users visit https://aimeelan.azurewebsites.net
     │
     ▼
Azure Load Balancer → App Service → Flask handles the request
```

### What GitHub Actions Does

The workflow file `.github/workflows/main_aimeelan.yml` automates:

1. **Build stage:** Install Python dependencies, package the code
2. **Deploy stage:** Send the package to Azure using a publish profile (stored as a GitHub secret)

You never manually upload files. `git push` triggers everything.

### What Azure App Service Does

- Runs a Linux container with Python installed
- Executes your startup command: `gunicorn --bind=0.0.0.0:8000 --timeout 600 app:app`
- `gunicorn` spawns worker processes, each running the Flask `app` object from `app.py`
- Azure's load balancer routes HTTPS traffic (port 443) to gunicorn (port 8000)
- Provides automatic SSL certificates (HTTPS)
- Auto-restarts if the app crashes

---

## Platform Comparison

| Feature | Run Locally | Railway | Render | Personal Azure | VPS |
|---------|------------|---------|--------|---------------|-----|
| **Cost** | Free | Free ($5 credit) | Free (750 hrs) | Free 12 months → ~$44/mo | ~$5/mo |
| **PostgreSQL** | Self-managed | Included free | Included free | ~$15/mo | Self-managed |
| **Redis** | Self-managed | Included free | Included free | ~$16/mo | Self-managed |
| **Auto-deploy from git push** | No | Yes (built-in) | Yes (built-in) | Yes (GitHub Actions) | Manual or self-setup |
| **Custom domain** | No | Yes | Yes | Yes | Yes |
| **SSL/HTTPS** | No | Auto | Auto | Auto | Manual (Let's Encrypt) |
| **Uptime** | When laptop is on | 24/7 | 24/7 | 24/7 | 24/7 |
| **Public access** | No (localhost only) | Yes | Yes | Yes | Yes |
| **Difficulty** | Easy | Easy | Easy | Medium | Hard |
| **Best for** | Development/testing | Free personal hosting | Free personal hosting | Exact same as current | Full control |

---

## All Deployment Methods at a Glance

```
                    Your Code (on GitHub)
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                  │
    Run Locally      Cloud Platform       Own Server
         │                 │                  │
   python app.py    git push triggers     SSH + gunicorn
         │           auto-deploy              │
         ▼                 ▼                  ▼
   localhost:5000    xxx.railway.app     your-ip:8000
   Only you see it   Everyone can visit  Everyone can visit
   Free              Free                ~$5/month
   For testing       For production      Full control
```

---

## Environment Variables Reference

| Variable | Required? | Description | Example |
|----------|-----------|-------------|---------|
| `AZURE_POSTGRESQL_CONNECTIONSTRING` | Yes | PostgreSQL connection string (any format) | `host=localhost dbname=portfoliodb user=postgres password=postgres` or `postgresql://user:pass@host/db` |
| `AZURE_REDIS_CONNECTIONSTRING` | No | Redis connection string | `redis://localhost:6379/0` or `rediss://:pass@host:6380/0` |
| `SECRET_KEY` | Recommended | Flask session encryption key | Any long random string |
| `ADMIN_USER` | No (default: `admin`) | Admin login username | `admin` |
| `ADMIN_PASS_HASH` | Recommended | bcrypt hash of admin password | `$2b$12$...` |
| `ADMIN_PASS` | Fallback | Plain text admin password (if no hash) | `admin123` |
| `OWNER_EMAIL` | No | Email for contact notifications | `you@gmail.com` |
| `SMTP_SERVER` | No | SMTP server for sending email | `smtp.gmail.com` |
| `SMTP_PORT` | No (default: 587) | SMTP port | `587` |
| `SMTP_USER` | No | SMTP login username | `you@gmail.com` |
| `SMTP_PASS` | No | SMTP password (Gmail App Password) | 16-character app password |
| `GITHUB_USERNAME` | No (default: `hahAI111`) | GitHub user for project sync | `hahAI111` |
| `GITHUB_TOKEN` | No | GitHub PAT for higher API rate limits | `ghp_xxxx` |
| `GITHUB_SYNC_INTERVAL` | No (default: 21600) | Seconds between auto-syncs | `21600` (6 hours) |

---

## FAQ

**Q: What is the absolute minimum to run the website?**
A: Python + PostgreSQL + the code + one environment variable (`AZURE_POSTGRESQL_CONNECTIONSTRING`). Redis, email, GitHub sync are all optional.

**Q: Do I need to learn Docker?**
A: No. Docker is just a convenient way to run PostgreSQL locally. You can install PostgreSQL directly, or use a cloud platform where it's managed for you.

**Q: What is gunicorn and why is it needed?**
A: `gunicorn` is a production-grade Python HTTP server. Flask's built-in server (`python app.py`) is for development only — it can only handle one request at a time. `gunicorn` spawns multiple workers to handle concurrent users. Always use gunicorn in production.

**Q: Can I use a free platform permanently?**
A: Railway gives $5/month free credit (enough for a small portfolio). Render's free tier has a 750 hour/month limit and databases expire after 90 days (recreate free). For truly permanent free hosting, consider Fly.io or GitHub Pages (static only).

**Q: I deployed but the site shows an error. How do I debug?**
A: Check the platform's logs:
- Railway: Click your service → **Logs** tab
- Render: Click your service → **Logs** tab
- Azure: `az webapp log tail --name YOUR_APP --resource-group YOUR_RG`
- Local: Errors print directly in the terminal

Most common issues: missing environment variable, wrong database URL format, or database not accessible.

**Q: How do I update the website after deploying?**
A: Just `git push origin main`. All cloud platforms (Railway, Render, Azure) auto-redeploy when they detect new commits on `main`.

**Q: Can I point a custom domain to my site?**
A: Yes. Buy a domain (~$12/year from Namecheap or Cloudflare), then:
- Railway: Settings → Custom Domain → Add domain → Update DNS
- Render: Settings → Custom Domain → Add domain → Update DNS
- Azure: Custom domains → Add domain → Update DNS
All platforms provide free SSL certificates automatically.
