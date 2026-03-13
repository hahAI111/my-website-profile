# Azure Cloud Setup Guide — Step by Step

A complete, detailed guide to deploying this Flask portfolio website on Microsoft Azure. This guide reflects **how this project was actually built**: Azure Portal auto-creates most infrastructure (VNet, subnets, private DNS, private endpoints) when you create PostgreSQL and Redis. The only manual work on App Service is configuring the startup command and environment variables.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [What Azure Creates Automatically vs. What You Configure Manually](#2-what-azure-creates-automatically-vs-what-you-configure-manually)
3. [Prerequisites](#3-prerequisites)
4. [Step 1 — Create a Resource Group](#4-step-1--create-a-resource-group)
5. [Step 2 — Create Azure PostgreSQL Flexible Server](#5-step-2--create-azure-postgresql-flexible-server)
6. [Step 3 — Create Azure Cache for Redis](#6-step-3--create-azure-cache-for-redis)
7. [Step 4 — Create the Web App (App Service)](#7-step-4--create-the-web-app-app-service)
8. [Step 5 — Configure the Startup Command (Manual)](#8-step-5--configure-the-startup-command-manual)
9. [Step 6 — Configure Environment Variables (Manual)](#9-step-6--configure-environment-variables-manual)
10. [Step 7 — Set Up GitHub Actions CI/CD](#10-step-7--set-up-github-actions-cicd)
11. [Step 8 — Verify Deployment](#11-step-8--verify-deployment)
12. [Step 9 — Set Up Monitoring & Logs](#12-step-9--set-up-monitoring--logs)
13. [Understanding the Auto-Created Networking](#13-understanding-the-auto-created-networking)
14. [Deep Dive — Why Each Configuration Exists](#14-deep-dive--why-each-configuration-exists)
15. [Cost Estimation](#15-cost-estimation)
16. [Our Live Configuration Reference](#16-our-live-configuration-reference)
17. [Troubleshooting](#17-troubleshooting)

---

## 1. Architecture Overview

Here is the architecture of what you'll build:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Azure Resource Group                         │
│                    (aimee-test-env)                             │
│                                                                 │
│  ┌─────────────┐    VNet Integration    ┌──────────────────┐   │
│  │  App Service │◄─────────────────────►│  Virtual Network  │   │
│  │  (Linux,     │                       │  (auto-created)   │   │
│  │   Python)    │                       │                    │   │
│  └──────┬───────┘                       │  ┌──────────────┐ │   │
│         │                               │  │ Subnet       │ │   │
│         │ HTTPS                         │  │ (App Service)│ │   │
│         │                               │  └──────────────┘ │   │
│         ▼                               │  ┌──────────────┐ │   │
│  ┌──────────────┐                       │  │ Subnet       │ │   │
│  │   GitHub     │                       │  │ (PostgreSQL) │ │   │
│  │   Actions    │                       │  └──────────────┘ │   │
│  │   CI/CD      │                       │  ┌──────────────┐ │   │
│  └──────────────┘                       │  │ Subnet       │ │   │
│                                          │  │ (Redis PE)   │ │   │
│  ┌──────────────────┐  Private Link     │  └──────────────┘ │   │
│  │  PostgreSQL       │◄────────────────►│                    │   │
│  │  Flexible Server  │                  └──────────────────┘   │
│  │  (v14, GP tier)   │                                         │
│  └──────────────────┘                                          │
│                                                                 │
│  ┌──────────────────┐  Private Endpoint                        │
│  │  Azure Cache for │◄─────────────────────────────────────    │
│  │  Redis (Basic C0) │                                         │
│  └──────────────────┘                                          │
│                                                                 │
│  ┌──────────────────┐                                          │
│  │  Private DNS      │  privatelink.postgres.database.azure.com│
│  │  Zones (auto)     │  privatelink.redis.cache.windows.net    │
│  └──────────────────┘                                          │
└─────────────────────────────────────────────────────────────────┘
```

**Key takeaway:** The diagram looks complex, but most of the networking (VNet, subnets, private DNS zones, private endpoints, NSGs) is **automatically created by Azure** when you create PostgreSQL and Redis through the Portal. You don't need to set any of that up manually.

---

## 2. What Azure Creates Automatically vs. What You Configure Manually

This is the most important section. Many tutorials make Azure look harder than it is by showing manual VNet/subnet/NSG setup. In reality, the Azure Portal wizard does it for you.

### Auto-Created by Azure (you just click through the wizard)

When you create **PostgreSQL Flexible Server** with "Private access", Azure automatically creates:
- ✅ Virtual Network (VNet) with address space
- ✅ PostgreSQL subnet with proper delegation
- ✅ Private DNS zone (`privatelink.postgres.database.azure.com`)
- ✅ DNS zone VNet link
- ✅ Network Security Groups (NSGs)

When you create **Azure Cache for Redis** with "Private Endpoint", Azure automatically creates:
- ✅ Redis private endpoint
- ✅ Cache subnet in the existing VNet
- ✅ Private DNS zone (`privatelink.redis.cache.windows.net`)
- ✅ Network interface for the private endpoint
- ✅ NSG for the cache subnet

When you create **App Service** and connect it to the VNet, Azure automatically creates:
- ✅ App Service subnet in the existing VNet
- ✅ VNet integration configuration
- ✅ NSG for the app subnet

### Manually Configured by You (the actual work)

On the **App Service**, you only need to do two things:

| Manual Step | What | Why |
|-------------|------|-----|
| **Startup Command** | `gunicorn --bind=0.0.0.0:8000 --timeout 600 app:app` | Tell Azure how to run your Flask app |
| **Environment Variables** | App Settings + Connection Strings | Give your app the database passwords, email config, etc. |

That's it. Everything else is handled by Azure's provisioning wizards.

---

## 3. Prerequisites

Before you start, make sure you have:

| Requirement | How to Get It |
|-------------|---------------|
| **Azure Account** | Sign up at [azure.microsoft.com](https://azure.microsoft.com/free/) — free tier available |
| **GitHub Account** | [github.com](https://github.com/) |
| **Git** | [git-scm.com](https://git-scm.com/downloads) |
| **Python 3.10+** | [python.org](https://www.python.org/downloads/) |
| **Azure CLI** (optional) | [docs.microsoft.com/cli/azure/install](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) — only needed if you prefer command-line over Portal |

---

## 4. Step 1 — Create a Resource Group

A **Resource Group** is a logical container that holds all your Azure resources together. Think of it as a folder — when you delete the folder, everything inside gets deleted too. This makes cleanup easy.

### Azure Portal

1. Go to [portal.azure.com](https://portal.azure.com)
2. Click **"Create a resource"** → Search for **"Resource group"** → Click **Create**
3. Fill in:
   - **Subscription:** Select your subscription
   - **Resource group name:** `my-portfolio-rg`
   - **Region:** `Canada Central` (choose a region close to your target users)
4. Click **"Review + create"** → **"Create"**

> **Why this region?** All services must be in the same region for low latency and VNet connectivity. `canadacentral`, `eastus`, and `westeurope` are popular choices with full service availability.

---

## 5. Step 2 — Create Azure PostgreSQL Flexible Server

PostgreSQL stores all persistent data: visitors, analytics, blog posts, projects.

**When you create PostgreSQL with Private access, Azure will automatically create the VNet, subnet, and private DNS zone for you.** You do NOT need to create a VNet manually first.

### Azure Portal

1. Search for **"Azure Database for PostgreSQL Flexible Server"** → Click **Create**
2. **Basics** tab:
   - **Resource group:** `my-portfolio-rg`
   - **Server name:** `my-portfolio-db` (must be globally unique)
   - **Region:** `Canada Central`
   - **PostgreSQL version:** `14`
   - **Workload type:** `Development` (cheapest for personal projects)
   - **Compute + storage:**
     - Click **Configure server** → Select `Burstable` tier → `Standard_B1ms` (cheapest: 1 vCore, 2 GB RAM)
     - **Storage:** `32 GB`
   - **Admin username:** `pgadmin`
   - **Password:** Choose a strong password — **save it somewhere safe!**
3. **Networking** tab:
   - **Connectivity method:** Select **`Private access (VNet Integration)`**
   - Azure will show: "A new virtual network and a new subnet delegated to PostgreSQL will be created"
   - **Virtual network:** Click **Create new** → Give it any name (e.g., `my-portfolio-vnet`)
   - **Subnet:** Azure auto-creates a delegated subnet
   - **Private DNS zone:** Click **Create new** → Azure suggests `privatelink.postgres.database.azure.com`
   - Just accept the defaults — Azure handles the networking setup
4. Click **"Review + create"** → **"Create"**

   ⏱ This takes **5-10 minutes**.

### What Azure Auto-Created For You

After PostgreSQL finishes provisioning, go to your resource group. You'll see Azure created **all of these automatically**:

| Resource | Type | Why Azure Created It |
|----------|------|---------------------|
| `my-portfolio-db` | PostgreSQL Flexible Server | You requested this |
| `my-portfolio-vnet` | Virtual Network | Needed for private access |
| A subnet | Subnet (delegated to PostgreSQL) | Isolates the database traffic |
| `privatelink.postgres.database.azure.com` | Private DNS Zone | Resolves DB hostname to private IP |
| A VNet link | DNS Zone → VNet Link | Connects DNS zone to your VNet |
| An NSG | Network Security Group | Firewall rules for the subnet |

**You didn't have to configure any of this networking manually.** Azure's "Private access" wizard did it all.

### Create the Application Database

After the server is created, you need to create a database inside it:

**Portal:** Go to your PostgreSQL server → **Databases** → Click **+ Add** → Name: `portfolio`

**Or CLI:**
```bash
az postgres flexible-server db create \
  --resource-group my-portfolio-rg \
  --server-name my-portfolio-db \
  --database-name portfolio
```

### Note Your Connection String

Your connection string will look like this (you'll need it in Step 6):

```
host=my-portfolio-db.postgres.database.azure.com dbname=portfolio port=5432 
user=pgadmin password=YourStrongPassword123! sslmode=require
```

Each part of this connection string:

| Part | Meaning |
|------|---------|
| `host=...` | Azure-assigned hostname — resolves to a private IP inside the VNet |
| `dbname=portfolio` | The specific database name you created (a server can hold multiple databases) |
| `port=5432` | Standard PostgreSQL port |
| `user=pgadmin` | The admin username you set during creation |
| `password=...` | The password you set during creation |
| `sslmode=require` | Forces encrypted connection — even within the VNet, encrypts data in transit (defense in depth) |

> **Cost Tip:** `Standard_B1ms` (Burstable) costs ~$12-15/month. Our production setup uses `Standard_D2s_v3` (General Purpose, ~$125/month) which is more powerful but not necessary for a personal site.

---

## 6. Step 3 — Create Azure Cache for Redis

Redis caches analytics stats and blog posts to reduce database load and improve response time.

**Azure will automatically create a private endpoint, subnet, and DNS zone when you select Private Endpoint networking.** It reuses the VNet that was auto-created in Step 2.

### Azure Portal

1. Search for **"Azure Cache for Redis"** → Click **Create**
2. **Basics** tab:
   - **Resource group:** `my-portfolio-rg`
   - **DNS name:** `my-portfolio-cache` (must be globally unique)
   - **Location:** `Canada Central`
   - **Cache SKU:** `Basic`
   - **Cache size:** `C0 (250 MB)` — cheapest, perfect for caching
3. **Networking** tab:
   - **Connectivity method:** Select **`Private Endpoint`**
   - Click **"+ Add private endpoint"**:
     - **Name:** `my-portfolio-cache-pe` (or accept the auto-generated name)
     - **Virtual network:** Select the VNet that was auto-created with PostgreSQL (e.g., `my-portfolio-vnet`)
     - **Subnet:** Azure will create a new subnet automatically, or select an existing one
     - **Private DNS zone:** Azure suggests `privatelink.redis.cache.windows.net` — accept the default
4. **Advanced** tab:
   - **Non-SSL port (6379):** `Disabled` (use SSL only for security)
   - **Minimum TLS version:** `1.2`
5. Click **"Review + create"** → **"Create"**

   ⏱ This takes **15-20 minutes**.

### What Azure Auto-Created For You

| Resource | Type | Why Azure Created It |
|----------|------|---------------------|
| `my-portfolio-cache` | Redis Cache | You requested this |
| `my-portfolio-cache-pe` | Private Endpoint | Routes traffic through VNet instead of internet |
| A NIC | Network Interface | The private endpoint's network interface |
| A subnet | Subnet in existing VNet | Dedicated space for the private endpoint |
| `privatelink.redis.cache.windows.net` | Private DNS Zone | Resolves Redis hostname to private IP |
| An NSG | Network Security Group | Firewall rules for the cache subnet |

### Get Redis Access Key

After Redis is created, get the connection string:

**Portal:** Go to your Redis cache → **Settings** → **Access keys** → Copy **Primary connection string**

The format is:
```
my-portfolio-cache.redis.cache.windows.net:6380,password=YourAccessKey,ssl=True,abortConnect=False
```

Each part of this connection string:

| Part | Meaning |
|------|---------|
| `...redis.cache.windows.net` | Azure-assigned hostname for your Redis instance |
| `:6380` | SSL-encrypted port (6379 = unencrypted, disabled for security) |
| `password=...` | Access key (like a password) — Azure generates this, you copy it |
| `ssl=True` | Forces the client to use encrypted connection |
| `abortConnect=False` | If Redis is temporarily unreachable at startup, don't crash — retry in background |

> **Cost Note:** Basic C0 costs ~$16/month. There is no free tier for Azure Redis.

---

## 7. Step 4 — Create the Web App (App Service)

The App Service runs your Flask code. When you create it with VNet connectivity, Azure automatically integrates it with the existing VNet (auto-created in Step 2).

### Azure Portal

1. Search for **"App Service"** → Click **Create** → **Web App**
2. **Basics** tab:
   - **Resource group:** `my-portfolio-rg`
   - **Name:** `my-portfolio-app` (this becomes your URL: `my-portfolio-app.azurewebsites.net`)
   - **Publish:** `Code`
   - **Runtime stack:** `Python 3.12` (or latest stable)
   - **Operating system:** `Linux`
   - **Region:** `Canada Central`
   - **Pricing plan:** Click **Create new** → Select `Basic B1` ($13/month — cheapest that supports VNet)
3. **Deployment** tab:
   - **GitHub Actions:** Enable continuous deployment → connect your GitHub repo
4. **Networking** tab:
   - **Enable public access:** `On` (users need to reach your website from the internet)
   - **Enable network injection:** `On`
   - **Virtual network:** Select the VNet auto-created with PostgreSQL (e.g., `my-portfolio-vnet`)
   - **Subnet:** Azure will create a new subnet automatically for the App Service
5. Click **"Review + create"** → **"Create"**

### What Azure Auto-Created For You

| Resource | Type | Why Azure Created It |
|----------|------|---------------------|
| `my-portfolio-app` | App Service (Web App) | You requested this |
| An App Service Plan | Service Plan (Linux, B1) | Compute resources for your app |
| A subnet | Subnet in existing VNet | For App Service VNet integration |
| An NSG | Network Security Group | Firewall rules for the app subnet |
| A managed identity | User Assigned Identity | For secure Azure resource access |

> **Pricing Tiers Comparison:**
>
> | Tier | vCPU | RAM | VNet Support | Price/Month |
> |------|------|-----|------|-------------|
> | Free F1 | Shared | 1 GB | ❌ | $0 |
> | Basic B1 | 1 | 1.75 GB | ✅ | ~$13 |
> | Standard S1 | 1 | 1.75 GB | ✅ + Slots | ~$70 |
> | Premium P1v3 | 2 | 8 GB | ✅ + Scale | ~$130 |
>
> You need **at least Basic B1** because PostgreSQL and Redis are on a private VNet. Free/Shared tiers cannot connect to VNets.

---

## 8. Step 5 — Configure the Startup Command (Manual)

**This is one of the two things you must do manually.** Azure doesn't know how to run your Flask app — you need to tell it.

### What to Set

Go to your **App Service** → **Settings** → **Configuration** → **General settings** tab:

- **Startup Command:** `gunicorn --bind=0.0.0.0:8000 --timeout 600 app:app`

Click **Save**.

### How the Request Flows (The Big Picture)

To understand why this command looks this way, you need to see the full request path:

```
User's Browser                  Azure Platform                       Your Code
     │                               │                                  │
     │  HTTPS (port 443)             │                                  │
     ├──────────────────────────────►│  Azure Reverse Proxy             │
     │                               │  (handles SSL certificates,      │
     │                               │   load balancing automatically)  │
     │                               │         │                        │
     │                               │    Forwards to port 8000         │
     │                               │         │                        │
     │                               │         ▼                        │
     │                               │    Gunicorn (production server)  │
     │                               │    - manages worker processes    │
     │                               │    - handles concurrency         │
     │                               │    - auto-restarts crashed workers│
     │                               │         │                        │
     │                               │    Calls app.py → app object     │
     │                               │         │                        │
     │                               │         ▼                        │
     │                               │    Flask processes the request   │
     │                               │    (routes, DB queries, render)  │
     │                               │         │                        │
     │  Returns HTML/JSON            │◄────────┘                        │
     │◄──────────────────────────────┤                                  │
```

**Three layers, each with a job:**
- **Azure Reverse Proxy** → SSL termination, load balancing, health checks (you don't configure this)
- **Gunicorn** → process management, concurrency, crash recovery (this is what the startup command configures)
- **Flask** → your application logic, routes, database queries (this is your code in `app.py`)

### Why Not Just `python app.py`?

Flask's built-in server prints this warning when it starts:

```
 * WARNING: Do not use the development server in a production deployment.
 * Use a production WSGI server instead.
```

Here's why:

| | Flask Dev Server (`python app.py`) | Gunicorn (production) |
|---|---|---|
| **Concurrency** | Single-threaded — 1 request at a time. If User A loads a slow page, User B waits. | Multi-process — handles many requests at once. Each worker is independent. |
| **Crash Recovery** | If one error crashes the process, the entire site goes down until manually restarted. | If a worker crashes, Gunicorn automatically spawns a new one. Site stays up. |
| **Security** | Exposes debug information (stack traces, variable values) that attackers can exploit. | No debug info. Clean error pages. |
| **Performance** | Not optimized. Slow static file serving. | Optimized C-based HTTP parser. Pre-fork worker model. |

### Why Each Part of This Command Exists

```
gunicorn --bind=0.0.0.0:8000 --timeout 600 app:app
│         │          │         │              │   │
│         │          │         │              │   └── Flask variable name
│         │          │         │              └── Python file name
│         │          │         └── Worker timeout (seconds)
│         │          └── Port number
│         └── Network interface
└── WSGI server program
```

| Part | Value | Why It's Needed | What Happens Without It |
|------|-------|-----------------|------------------------|
| `gunicorn` | Gunicorn WSGI server | **Production HTTP server.** WSGI (Web Server Gateway Interface) is the standard protocol between Python web apps and HTTP servers. Gunicorn is a pre-fork worker model server — it starts multiple worker processes, each capable of handling requests independently. It's the industry standard for Flask/Django deployments. | Azure falls back to Flask's dev server: single-threaded, insecure, unstable. |
| `--bind=0.0.0.0` | Listen on all network interfaces | **`0.0.0.0`** = accept connections from ANY IP address, not just localhost. Azure's reverse proxy runs in a separate network namespace and connects to your app via an internal IP. | If bound to `127.0.0.1` (localhost), Azure's proxy can't reach your app → **502 Bad Gateway**. |
| `:8000` | Port 8000 | **Azure's hardcoded expectation.** Azure App Service (Linux) forwards incoming HTTPS traffic (port 443) to your app on port 8000. This port mapping is built into Azure's platform and cannot be changed. | Binding to any other port (e.g., 5000) → Azure sends traffic to 8000, nobody's listening → **503 Service Unavailable**. |
| `--timeout 600` | 600 seconds (10 min) | **Prevents timeout during first startup.** When the app starts cold, it: (1) creates 9 database tables, (2) seeds 5 blog posts, (3) connects to PostgreSQL + Redis. This can take 30-60 seconds. The default Gunicorn timeout is only 30 seconds. | Default 30s timeout → first-time DB initialization exceeds it → Gunicorn kills the worker → **503 error loop**. |
| `app` (first) | Python module name | The file `app.py` → Python module `app` (drop the `.py`). Gunicorn runs `import app` to load your code. | `ModuleNotFoundError` → Gunicorn can't start. |
| `app` (second) | Flask variable name | Inside `app.py`, the line `app = Flask(__name__)` creates a Flask application object called `app`. Gunicorn looks for this variable and calls it as a WSGI application. | `AppImportError: Failed to find attribute 'app'` → Gunicorn can't start. |

### Analogy / 类比

```
Gunicorn  = Restaurant manager    / 餐厅经理（管理多个服务员，有人请假自动补人）
Flask     = Chef                  / 厨师（只管做菜）
app.py    = The kitchen           / 厨房
0.0.0.0   = Front door wide open  / 大门敞开（谁都能进来点餐）
:8000     = Street address #8000  / 餐厅门牌号（Azure 知道去 8000 号找你）
timeout   = 10-min max prep time  / 做一道菜最多等 10 分钟，超时就重做
```

Flask's dev server is like the chef doing everything alone — cooking, taking orders, washing dishes. One customer at a time. Gunicorn is the manager who hires a team so the restaurant can serve many customers simultaneously.

Flask 自带的服务器就像厨师一个人又做菜又端盘子又收银——同时只能服务一个客人。Gunicorn 就是请了一个经理来管理前厅，让餐厅能同时接待很多客人。

---

## 9. Step 6 — Configure Environment Variables (Manual)

**This is the second thing you must do manually.** Your Flask app needs database connections, email credentials, and other secrets that should never be in code.

### Why Environment Variables Instead of Hardcoding?

```python
# ❌ NEVER do this — secrets in code get pushed to GitHub
conn = psycopg2.connect("host=server.azure.com password=MySecret123")

# ✅ The correct way — read from environment variables
conn_str = os.environ.get("AZURE_POSTGRESQL_CONNECTIONSTRING")
conn = psycopg2.connect(conn_str)
```

Azure App Settings are injected as **environment variables** at runtime. They are:
- **Encrypted at rest** — stored securely in Azure's infrastructure
- **Not in your code** — never accidentally committed to Git
- **Easy to change** — update without redeploying code
- **Slot-specific** — can have different values for staging vs. production

### How to Configure

Go to your **App Service** → **Settings** → **Environment variables**

#### App Settings (click "+ Add" for each)

| Name | Example Value | Why It's Needed |
|------|---------------|----------------|
| `OWNER_EMAIL` | `you@example.com` | **Contact form recipient.** When visitors submit the contact form, the app sends an email notification to this address. Without it, contact form submissions are saved to the database but no email is sent. |
| `SMTP_SERVER` | `smtp.gmail.com` | **Email server hostname.** The app uses SMTP (Simple Mail Transfer Protocol) to send emails. Gmail's SMTP server is `smtp.gmail.com`. If you use Outlook, it would be `smtp.office365.com`. |
| `SMTP_PORT` | `587` | **Email server port.** Port 587 is the standard SMTP port for TLS-encrypted email submission. Port 465 is for SSL. Port 25 is unencrypted (blocked by most providers). Always use 587 with STARTTLS. |
| `SMTP_USER` | `you@gmail.com` | **Email sender account.** The "from" address for outgoing emails. Must be a real Gmail account that you control. |
| `SMTP_PASS` | `xxxx xxxx xxxx xxxx` | **Gmail App Password (NOT your Gmail login password).** Google requires a 16-character "App Password" for third-party apps. This is a separate credential that only works for SMTP. See instructions below for how to generate one. |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` | **Auto-install Python dependencies.** Tells Kudu (Azure's deployment engine) to run `pip install -r requirements.txt` during deployment. Without this, your app has no packages (no Flask, no psycopg2, etc.) and crashes immediately. |

#### Connection Strings (click "+ Add" for each)

| Name | Example Value | Type | Why It's Needed |
|------|---------------|------|----------------|
| `AZURE_POSTGRESQL_CONNECTIONSTRING` | `host=my-db.postgres.database.azure.com dbname=portfolio port=5432 user=pgadmin password=YourPwd sslmode=require` | `PostgreSQL` | **Database connection.** Contains the server address, database name, credentials, and SSL mode. `sslmode=require` ensures the connection is encrypted. The app reads this to connect to PostgreSQL on startup. |
| `azure_redis_cache` | `my-cache.redis.cache.windows.net:6380,password=Key,ssl=True,abortConnect=False` | `Custom` | **Redis connection.** Port `6380` = SSL port (not 6379 which is unencrypted). `ssl=True` enforces encryption. `abortConnect=False` means the app won't crash if Redis is temporarily unavailable — it retries in the background. |

Click **"Apply"** → **"Confirm"** to save all settings. The app will restart automatically.

### Why Connection Strings Are Separate from App Settings

Azure has two categories of environment variables:

| Category | Stored As | Prefix Added | Purpose |
|----------|-----------|--------------|---------|
| **App Settings** | `os.environ["NAME"]` | None | General config (email, flags) |
| **Connection Strings** | `os.environ["CUSTOMCONNSTR_NAME"]` or `os.environ["POSTGRESQLCONNSTR_NAME"]` | Type prefix | Database/service connections — marked as "sensitive" in Azure Portal, hidden by default |

Connection strings get a prefix based on their type: `POSTGRESQLCONNSTR_`, `CUSTOMCONNSTR_`, `SQLCONNSTR_`, etc. The app code accounts for this when reading environment variables.

### How to Get a Gmail App Password

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Enable **2-Step Verification** if not already on
3. Search for **"App passwords"**
4. Create a new app password → Name it `Azure Portfolio`
5. Copy the 16-character password (format: `xxxx xxxx xxxx xxxx`)
6. Use this as `SMTP_PASS`

> **Security Warning:** Never commit passwords or connection strings to Git. Always use App Settings.

---

## 10. Step 7 — Set Up GitHub Actions CI/CD

Continuous deployment means every `git push` to `main` automatically deploys to Azure. You don't need to manually upload files or run deploy commands — GitHub Actions handles everything.

### How CI/CD Works (The Concept)

```
You: git push                Build Server (GitHub)              Azure App Service
     │                              │                                 │
     │  push to main branch         │                                 │
     ├─────────────────────────────►│                                 │
     │                              │  1. Download your code          │
     │                              │  2. Install Python              │
     │                              │  3. pip install requirements    │
     │                              │  4. Zip everything              │
     │                              │  5. Upload to Azure ───────────►│
     │                              │                                 │  6. Unzip + restart
     │                              │                                 │  7. Site is live!
     │  ✅ Done                      │                                 │
```

**Why not deploy from your laptop directly?** CI/CD ensures:
- The build happens in a clean environment (no "works on my machine" issues)
- Every team member's push triggers the same deploy process
- You have a log of every deployment in GitHub Actions

### Step 7a — Get Publish Profile

1. Go to your **App Service** → **Overview** → Click **"Download publish profile"**
2. This downloads an XML file containing deployment credentials

> **What is a Publish Profile?** It's an XML file containing the URL, username, and password that GitHub needs to upload your code to Azure. Think of it as a "deployment key" — anyone with this file can deploy to your App Service.

### Step 7b — Add GitHub Secret

1. Go to your GitHub repository → **Settings** → **Secrets and variables** → **Actions**
2. Click **"New repository secret"**
   - **Name:** `AZUREAPPSERVICE_PUBLISHPROFILE`
   - **Value:** Paste the **entire contents** of the publish profile XML file
3. Click **"Add secret"**

> **Why a GitHub Secret?** Secrets are encrypted and never shown in logs. If you put the publish profile directly in your workflow file, anyone who can see your repo could deploy (or attack) your Azure app.

### Step 7c — Create GitHub Actions Workflow

Create the file `.github/workflows/main_aimeelan.yml` in your repository:

```yaml
# --- TRIGGER ---
# When does this workflow run?
name: Build and deploy Python app to Azure Web App

on:
  push:
    branches:
      - main            # Runs automatically when you push to the main branch
  workflow_dispatch:     # Also allows manual trigger from GitHub Actions tab

jobs:
  # --- JOB 1: BUILD ---
  # Why a separate build job? It runs in a clean environment, ensures the code
  # compiles and dependencies install correctly BEFORE attempting deployment.
  # If the build fails, the deploy job never runs (fail fast).
  build:
    runs-on: ubuntu-latest    # Uses a fresh Ubuntu VM provided by GitHub (free)
    steps:
      - uses: actions/checkout@v4    # Downloads your repo code onto the VM

      - name: Set up Python version
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'     # Installs Python 3.12 on the VM

      - name: Create and start virtual environment
        run: |
          python -m venv venv        # Creates isolated Python environment
          source venv/bin/activate   # Activates it (so pip installs go there)

      - name: Install dependencies
        run: pip install -r requirements.txt   # Installs Flask, psycopg2, etc.
        # This verifies all dependencies resolve correctly before deploying

      - name: Zip artifact for deployment
        run: zip release.zip ./* -r
        # Zips all project files into one archive for faster upload
        # Azure expects a zip package for deployment

      - name: Upload artifact for deployment jobs
        uses: actions/upload-artifact@v4
        with:
          name: python-app
          path: |
            release.zip
            !venv/             # Excludes venv/ — Azure rebuilds it from
                               # requirements.txt during deployment
        # "Artifact" = the built package passed from build job → deploy job

  # --- JOB 2: DEPLOY ---
  # Only runs if build succeeds (needs: build).
  # Uses the publish profile secret to authenticate with Azure.
  deploy:
    runs-on: ubuntu-latest
    needs: build              # Waits for build job to succeed first
    environment:
      name: 'Production'      # GitHub environment for deployment protection rules
      url: ${{ steps.deploy-to-webapp.outputs.webapp-url }}

    steps:
      - name: Download artifact from build job
        uses: actions/download-artifact@v4
        with:
          name: python-app    # Downloads the zip from the build job

      - name: Unzip artifact for deployment
        run: unzip release.zip    # Extracts the zip for deployment

      - name: 'Deploy to Azure Web App'
        uses: azure/webapps-deploy@v3
        id: deploy-to-webapp
        with:
          app-name: 'my-portfolio-app'   # Your App Service name
          slot-name: 'Production'         # Deploy to production slot
          publish-profile: ${{ secrets.AZUREAPPSERVICE_PUBLISHPROFILE }}
          # ↑ Reads the publish profile from GitHub Secrets (encrypted)
          # This authenticates the deployment — without it, Azure rejects the upload
```

### Why Two Separate Jobs (Build → Deploy)?

| Reason | Explanation |
|--------|-------------|
| **Fail fast** | If `pip install` fails (e.g., a typo in requirements.txt), the deploy never happens. You don't waste time deploying broken code. |
| **Clean separation** | Build = "does my code work?" Deploy = "push it to Azure." Different concerns, different jobs. |
| **Reusability** | You could add more deploy targets (staging, production) that all reuse the same build artifact. |
| **Audit trail** | GitHub shows which job failed, making debugging faster. |

### Step 7d — Push and Watch

```bash
git add -A
git commit -m "Add GitHub Actions CI/CD"
git push
```

Go to your GitHub repository → **Actions** tab. You should see the workflow running:

```
Build and deploy Python app to Azure Web App
├── build    ✅ (1-2 minutes)
└── deploy   ✅ (2-3 minutes)
```

After both jobs complete, your site is live at `https://my-portfolio-app.azurewebsites.net`!

---

## 11. Step 8 — Verify Deployment

### Check the Website

Open your browser and go to: `https://my-portfolio-app.azurewebsites.net`

You should see the **Visitor Verification** page asking for name and email.

### Check Application Logs

```bash
az webapp log tail \
  --name my-portfolio-app \
  --resource-group my-portfolio-rg
```

Look for these key lines in the startup logs:

```
[INFO] Starting gunicorn 21.2.0
[INFO] Listening at: http://0.0.0.0:8000
[INFO] Using worker: sync
Connected to PostgreSQL successfully
Redis connected successfully
Created 9 tables
Seeded 5 blog posts
```

### Common Startup Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| **503 Service Unavailable** | App is still starting | Wait 2-3 minutes, check logs |
| **Application Error** | Missing environment variables | Check App Settings and Connection Strings |
| **Connection refused (PostgreSQL)** | VNet not configured | Verify VNet integration and subnet delegations |
| **Redis connection timeout** | Private endpoint not working | Check private DNS zone configuration |

### Test the Full Flow

1. **Verify page** → Enter name and email → Should redirect to portfolio
2. **Blog** → Click `/blog` → Should show 5 seed posts
3. **Projects** → Click `/projects` → Will be empty until you sync
4. **Admin** → Go to `/admin` → Login with admin credentials
5. **Admin dashboard** → Should show visitor count, charts load correctly

---

## 12. Step 9 — Set Up Monitoring & Logs

### Enable HTTP Logging

```bash
az webapp config appsettings set \
  --resource-group my-portfolio-rg \
  --name my-portfolio-app \
  --settings WEBSITE_HTTPLOGGING_RETENTION_DAYS=7
```

> **Why 7 days?** HTTP logs record every request (URL, status code, response time, IP). 7 days gives you enough history to debug recent issues without accumulating storage costs. Most problems are noticed within a week.

### Enable Diagnostic Logging

In the Azure Portal:

1. Go to your **App Service** → **Monitoring** → **Diagnostic settings**
2. Click **"+ Add diagnostic setting"**
3. Check:
   - ✅ **AppServiceHTTPLogs** — Every HTTP request/response (like nginx access logs)
   - ✅ **AppServiceConsoleLogs** — stdout/stderr output from Gunicorn and Flask (your `print()` statements)
   - ✅ **AppServiceAppLogs** — Application-level logs (errors, warnings)
4. Send to: **Log Analytics workspace** (create one if needed)

> **What is Log Analytics?** A centralized log storage and query service in Azure. You can search across all your logs using KQL (Kusto Query Language). Example: find all 500 errors in the last 24 hours.

### Monitor PostgreSQL

```bash
# Check server status
az postgres flexible-server show \
  --resource-group my-portfolio-rg \
  --name my-portfolio-db \
  --query "{State:state, FQDN:fullyQualifiedDomainName}" -o table
```

### Monitor Redis

```bash
# Check Redis status and memory
az redis show \
  --resource-group my-portfolio-rg \
  --name my-portfolio-cache \
  --query "{State:provisioningState, HostName:hostName, Port:sslPort}" -o table
```

---

## 13. Understanding the Auto-Created Networking

This section explains the networking infrastructure that Azure created automatically in Steps 2-4. You don't need to do anything here — it's just for understanding.

### How Traffic Flows

```
  Internet Users
       │
       │ HTTPS (port 443)
       ▼
┌──────────────────┐
│   App Service    │  ← Public endpoint (users connect here)
│  (webapp-subnet) │
└──────┬───────────┘
       │
       │ VNet Integration (private traffic, NOT over internet)
       ▼
┌──────────────────────────────────────┐
│         Virtual Network              │
│         (auto-created)               │
│                                      │
│  ┌─────────────────┐                 │
│  │ PostgreSQL       │  Private DNS:  │
│  │ subnet           │  hostname →    │
│  │ (auto-created)   │  private IP    │
│  └─────────────────┘  (10.x.x.x)    │
│                                      │
│  ┌─────────────────┐                 │
│  │ Redis private    │  Private DNS:  │
│  │ endpoint subnet  │  hostname →    │
│  │ (auto-created)   │  private IP    │
│  └─────────────────┘  (10.x.x.x)    │
└──────────────────────────────────────┘
```

### Why Private Networking Matters

**Without VNet (public access):**
```
App Service ──── internet ────► PostgreSQL (public IP)
                                 └── anyone with the IP could try to connect
                                 └── traffic exposed to network sniffing
```

**With VNet (private access, our setup):**
```
App Service ──── VNet (private) ────► PostgreSQL (private IP only)
                                       └── NO public IP exists
                                       └── only resources in the VNet can connect
                                       └── traffic never leaves Azure's backbone
```

The database has **no public IP at all**. Even if someone knows the hostname, they can't connect because DNS resolves to a private IP that's only routable within the VNet.

### Private DNS Zones — How Hostname Resolution Works

Azure auto-created two Private DNS Zones:

| DNS Zone | Resolves | To |
|----------|----------|----|
| `privatelink.postgres.database.azure.com` | `my-db.postgres.database.azure.com` | `10.0.2.4` (private IP) |
| `privatelink.redis.cache.windows.net` | `my-cache.redis.cache.windows.net` | `10.0.3.4` (private IP) |

**How it works:** When the App Service code calls `psycopg2.connect("host=my-db.postgres.database.azure.com ...")`, the DNS lookup goes through the Private DNS Zone (because the App Service is in the VNet). The zone returns a private IP like `10.0.2.4` instead of a public IP. The connection then flows entirely within the VNet.

### Network Security Groups (NSGs)

Azure auto-created NSGs for each subnet. These are like firewalls that control:
- **Inbound rules:** What traffic can enter the subnet
- **Outbound rules:** What traffic can leave the subnet

The default rules allow traffic within the VNet and block traffic from the internet to the database/cache subnets. You don't need to modify these for a standard setup.

### Verify Networking (Optional)

```bash
# Check VNet integration is active
az webapp vnet-integration list \
  --name my-portfolio-app \
  --resource-group my-portfolio-rg \
  -o table

# From App Service console (Portal → Development Tools → Console):
nslookup my-portfolio-db.postgres.database.azure.com
# Should return a private IP (10.x.x.x), not a public IP
```

---

## 14. Deep Dive — Why Each Configuration Exists

Here's a comprehensive reference explaining the principle behind every setting in this project.

### App Service Settings

| Setting | Value | Principle |
|---------|-------|-----------|
| **Runtime: Python 3.12+** | `PYTHON\|3.14` | Azure needs to know which language runtime to install. Python apps need the Python interpreter, pip, and standard library pre-installed in the container. |
| **OS: Linux** | `app,linux` | Python web apps run on Linux containers in Azure. Linux is lighter weight (~100MB) vs Windows (~1GB), starts faster, and is the standard for Python deployments. |
| **HTTPS Only** | `true` | Forces all HTTP requests to redirect to HTTPS. Without this, user data (login credentials, emails) would be sent in plain text over the network. |
| **Min TLS: 1.2** | `1.2` | TLS (Transport Layer Security) encrypts HTTPS traffic. Version 1.0 and 1.1 have known vulnerabilities. 1.2 is the minimum secure version as of 2024. |
| **FTPS Only** | `FtpsOnly` | FTP transfers files unencrypted. FTPS adds SSL encryption. "FtpsOnly" prevents accidental unencrypted file uploads to the server. |
| **Always On: No** | `false` | "Always On" keeps the app warm (no cold starts). It costs more because the app never idles. For a personal portfolio with low traffic, cold starts are acceptable to save cost. |

### Startup Command — Every Parameter Explained

```
gunicorn --bind=0.0.0.0:8000 --timeout 600 app:app
```

| Parameter | Principle |
|-----------|----------|
| `gunicorn` | **WSGI server.** WSGI (Web Server Gateway Interface) is the standard protocol between Python web apps and HTTP servers. Flask implements WSGI. Gunicorn is a multi-process WSGI server that can handle many concurrent requests. Flask's built-in server (`flask run`) is single-threaded and insecure — it even prints "WARNING: Do not use the development server in a production deployment." |
| `--bind=0.0.0.0` | **Network interface binding.** `0.0.0.0` means "listen on all network interfaces" — this allows Azure's reverse proxy to connect to the app. If you used `127.0.0.1` (localhost), only processes inside the same container could connect, and Azure's proxy would get "connection refused". |
| `:8000` | **Port number.** Azure App Service for Linux expects Python apps to listen on port 8000. Azure's front-end load balancer receives HTTPS traffic on port 443 and forwards it internally to port 8000. This port mapping is hardcoded in Azure's platform. |
| `--timeout 600` | **Worker timeout in seconds.** If a request takes longer than this to respond, Gunicorn kills the worker process and starts a new one. Default is 30 seconds. Our app needs more because: (1) first startup creates 9 DB tables + seeds 5 blog posts (~30-60s), (2) cold starts on Burstable VMs are slow, (3) large CSV exports may take time. 600s = 10 minutes of headroom. |
| `app:app` | **module:variable format.** First `app` = Python module name (file `app.py` → module `app`). Second `app` = the Flask application variable inside that module (`app = Flask(__name__)`). Gunicorn imports the module and calls the variable as a WSGI application. |

### Environment Variables — Every Setting Explained

| Variable | Principle |
|----------|-----------|
| `AZURE_POSTGRESQL_CONNECTIONSTRING` | **Connection string.** Contains host, database, port, username, password, and SSL mode in one string. The `sslmode=require` part forces encrypted connections — even within the VNet, defense in depth means encrypting data in transit. |
| `azure_redis_cache` | **Redis connection.** Uses port 6380 (SSL) not 6379 (plain). `abortConnect=False` is critical — if Redis is temporarily down during app startup, the app still starts and retries Redis later instead of crashing. |
| `OWNER_EMAIL` | **Separation of config from code.** The email recipient could change without code changes. Hardcoding it would require a full redeployment just to change an email address. |
| `SMTP_*` settings | **Email delivery.** SMTP (Simple Mail Transfer Protocol) is how email is sent between servers. Port 587 uses STARTTLS (starts unencrypted, upgrades to TLS). The App Password is used because Gmail blocks less-secure "password only" login for third-party apps — App Passwords are scoped credentials that can be revoked independently. |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | **Build automation.** SCM = Source Code Management (Azure's deployment engine, called Kudu). This flag tells Kudu to detect `requirements.txt` and run `pip install` during deployment. Without it, your app has zero Python packages installed and crashes with `ModuleNotFoundError: No module named 'flask'`. |
| `WEBSITE_HTTPLOGGING_RETENTION_DAYS` | **Log retention policy.** HTTP logs (request URL, status code, response time) are stored for this many days. 7 days is enough to debug recent issues without accumulating large storage costs. |

### PostgreSQL Settings

| Setting | Principle |
|---------|-----------|
| **Version 14** | PostgreSQL 14 is a stable, well-tested release with good JSON support, improved performance, and long-term security patches. Not bleeding edge (less bugs), not too old (has modern features). |
| **Burstable tier** | "Burstable" means the VM normally runs at a baseline CPU level but can burst to full speed for short periods. Perfect for web apps: most requests are simple (low CPU), but occasionally a complex query or export needs more power. Costs much less than "General Purpose" which reserves full CPU all the time. |
| **Backup: 7 days** | Azure automatically takes daily backups and keeps them for 7 days. If your database gets corrupted or you accidentally delete data, you can restore to any point within the last 7 days. This is built-in and free with any PostgreSQL Flexible Server. |
| **HA: Disabled** | High Availability creates a standby replica in another availability zone for automatic failover. For a personal portfolio, downtime of a few minutes is acceptable. HA doubles the cost. |
| **sslmode=require** | Even though traffic stays within the VNet (never touches the internet), we still encrypt the PostgreSQL connection. This is "defense in depth" — if somehow network isolation fails, the data is still encrypted. It also protects against internal threats. |

### Redis Settings

| Setting | Principle |
|---------|-----------|
| **Basic C0** | The smallest Redis instance (250 MB, shared infrastructure). Sufficient for caching stats and blog posts. "Basic" means no replication or SLA — acceptable for a cache (if Redis dies, the app falls back to direct DB queries). |
| **SSL Port 6380** | Port 6379 is Redis's unencrypted port. Port 6380 is the SSL-encrypted port. We disable 6379 entirely so that all Redis traffic is encrypted, even within the private VNet. |
| **Min TLS 1.2** | Same as App Service — prevents connections using outdated, vulnerable TLS versions. |
| **Private Endpoint** | Unlike PostgreSQL (which uses VNet Integration directly), Redis uses a "Private Endpoint" — a virtual NIC inside the VNet that gets a private IP. The effect is the same: Redis is only accessible from within the VNet, with no public IP. |

---

## 15. Cost Estimation

Here is the monthly cost breakdown for the recommended setup:

| Resource | SKU | Monthly Cost (USD) |
|----------|-----|--------------------|
| App Service Plan | Basic B1 (1 vCore, 1.75 GB) | ~$13 |
| PostgreSQL Flexible Server | Burstable B1ms (1 vCore, 2 GB) | ~$12 |
| Azure Cache for Redis | Basic C0 (250 MB) | ~$16 |
| VNet / Subnets | — | Free |
| Private DNS Zones | 2 zones | ~$1 |
| GitHub Actions | 2,000 min/month free | Free |
| **Total** | | **~$42/month** |

### Ways to Reduce Costs

- **Stop when not in use:** Stop the App Service and PostgreSQL during non-work hours
  ```bash
  az webapp stop --name my-portfolio-app --resource-group my-portfolio-rg
  az postgres flexible-server stop --name my-portfolio-db --resource-group my-portfolio-rg
  ```
- **Free tier App Service:** If you don't need VNet integration, use the Free F1 tier ($0)
- **PostgreSQL public access:** Skip VNet/private DNS, allow public IP with firewall rules (less secure but simpler)
- **Skip Redis:** The app works without Redis — it just falls back to direct DB queries

### Clean Up Everything (Delete All Resources)

To remove all resources and stop billing:

```bash
az group delete --name my-portfolio-rg --yes --no-wait
```

> ⚠️ **Warning:** This is irreversible. All data in PostgreSQL and Redis will be permanently deleted.

---

## 16. Our Live Configuration Reference

Here is the actual Azure configuration used by this project for reference:

### Resource Group

| Property | Value |
|----------|-------|
| Name | `aimee-test-env` |
| Location | `northcentralus` (resources in `canadacentral`) |

### App Service

| Property | Value |
|----------|-------|
| Name | `aimeelan` |
| URL | `https://aimeelan.azurewebsites.net` |
| OS | Linux |
| Runtime | Python 3.14 |
| Startup Command | `gunicorn --bind=0.0.0.0:8000 --timeout 600 app:app` |
| HTTPS Only | Yes |
| Always On | No |
| FTPS State | FtpsOnly |
| Min TLS | 1.2 |
| SCM Type | GitHubAction |
| VNet Integration | `vnet-zqopjmgp / subnet-foithjjx` |

### App Settings

| Name | Purpose |
|------|---------|
| `OWNER_EMAIL` | Contact notification recipient |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | Auto pip install |
| `SMTP_PASS` | Gmail App Password |
| `SMTP_PORT` | 587 |
| `SMTP_SERVER` | smtp.gmail.com |
| `SMTP_USER` | Gmail sender account |
| `WEBSITE_HTTPLOGGING_RETENTION_DAYS` | 7-day log retention |

### Connection Strings

| Name | Type |
|------|------|
| `AZURE_POSTGRESQL_CONNECTIONSTRING` | PostgreSQL |
| `azure_redis_cache` | Custom |

### PostgreSQL Flexible Server

| Property | Value |
|----------|-------|
| Name | `aimeelan-server` |
| FQDN | `aimeelan-server.postgres.database.azure.com` |
| Version | 14 |
| SKU | Standard_D2s_v3 (General Purpose) |
| vCores | 2 |
| Storage | 128 GB |
| Backup Retention | 7 days |
| High Availability | Disabled |
| Database | `aimeelan-database` |

### Redis Cache

| Property | Value |
|----------|-------|
| Name | `aimee-cache` |
| Hostname | `aimee-cache.redis.cache.windows.net` |
| SKU | Basic C0 (250 MB) |
| SSL Port | 6380 |
| Non-SSL Access | Disabled |
| Min TLS | 1.2 |
| Private Endpoint | `aimee-cache-pe` |

### CI/CD

| Property | Value |
|----------|-------|
| Source | GitHub |
| Repository | `hahAI111/aimeewebpage` |
| Branch | `main` |
| Method | GitHub Actions |

---

## 17. Troubleshooting

### "Application Error" after deployment

```bash
# Check recent logs
az webapp log tail --name my-portfolio-app --resource-group my-portfolio-rg

# Check if the app is running
az webapp show --name my-portfolio-app --resource-group my-portfolio-rg --query state
```

### PostgreSQL connection fails

```bash
# Check PostgreSQL server state
az postgres flexible-server show --name my-portfolio-db --resource-group my-portfolio-rg --query state

# Check if VNet integration is active
az webapp vnet-integration list --name my-portfolio-app --resource-group my-portfolio-rg -o table
```

**Common causes:**
- Wrong connection string format
- PostgreSQL is stopped (check server state)
- VNet integration not enabled on App Service
- Subnet delegation missing

### Redis connection fails

```bash
# Check Redis state
az redis show --name my-portfolio-cache --resource-group my-portfolio-rg --query provisioningState

# Verify private endpoint
az network private-endpoint show --name my-portfolio-cache-pe --resource-group my-portfolio-rg --query "{State:provisioningState}" -o table
```

**Common causes:**
- Wrong Redis access key in connection string
- Private endpoint not linked to DNS zone
- Using port `6379` instead of `6380` (SSL)

### GitHub Actions deployment fails

1. Go to your GitHub repo → **Actions** tab → Click the failed run
2. Check the **deploy** step error message
3. Common fixes:
   - Regenerate publish profile and update the GitHub secret
   - Make sure `requirements.txt` is in the repo root
   - Check for Python syntax errors in `app.py`

### Site is slow on first visit

This is normal. Azure App Service (Basic tier without Always On) takes 20-30 seconds to cold start. The app initializes:
1. Gunicorn starts
2. Flask initializes
3. PostgreSQL tables are checked/created (9 tables)
4. Blog posts are seeded (first run only)
5. Redis connection is established

Subsequent requests are fast (~50-200ms).

---

## Summary Checklist

Use this checklist to track your progress:

- [ ] Created Resource Group
- [ ] Created PostgreSQL Flexible Server (Azure auto-creates VNet, subnet, private DNS)
- [ ] Created application database inside PostgreSQL
- [ ] Created Azure Cache for Redis with Private Endpoint (Azure auto-creates subnet, private DNS)
- [ ] Created App Service with VNet integration (Azure auto-creates subnet)
- [ ] **[Manual]** Configured startup command: `gunicorn --bind=0.0.0.0:8000 --timeout 600 app:app`
- [ ] **[Manual]** Added App Settings (OWNER_EMAIL, SMTP_*, SCM_DO_BUILD_DURING_DEPLOYMENT)
- [ ] **[Manual]** Added Connection Strings (PostgreSQL, Redis)
- [ ] Set up GitHub Actions workflow
- [ ] Added publish profile as GitHub secret
- [ ] Pushed code and verified deployment
- [ ] Tested full user flow (verify → blog → admin)
- [ ] Enabled logging and monitoring

> Only 3 items are marked **[Manual]** — everything else is done through Azure's creation wizards with default settings.

**Congratulations!** Your Flask portfolio website is now running on Azure with enterprise-grade infrastructure. 🎉
