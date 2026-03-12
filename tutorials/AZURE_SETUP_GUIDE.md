# Azure Cloud Setup Guide — Step by Step

A complete, detailed guide to deploying this Flask portfolio website on Microsoft Azure from scratch. Covers every Azure resource you need: Resource Group, Virtual Network, App Service, PostgreSQL, Redis, CI/CD, and monitoring.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Step 1 — Create a Resource Group](#3-step-1--create-a-resource-group)
4. [Step 2 — Create a Virtual Network (VNet)](#4-step-2--create-a-virtual-network-vnet)
5. [Step 3 — Create Azure PostgreSQL Flexible Server](#5-step-3--create-azure-postgresql-flexible-server)
6. [Step 4 — Create Azure Cache for Redis](#6-step-4--create-azure-cache-for-redis)
7. [Step 5 — Create an App Service Plan](#7-step-5--create-an-app-service-plan)
8. [Step 6 — Create the Web App (App Service)](#8-step-6--create-the-web-app-app-service)
9. [Step 7 — Configure App Settings & Connection Strings](#9-step-7--configure-app-settings--connection-strings)
10. [Step 8 — Set Up GitHub Actions CI/CD](#10-step-8--set-up-github-actions-cicd)
11. [Step 9 — Configure Networking & Private Endpoints](#11-step-9--configure-networking--private-endpoints)
12. [Step 10 — Verify Deployment](#12-step-10--verify-deployment)
13. [Step 11 — Set Up Monitoring & Logs](#13-step-11--set-up-monitoring--logs)
14. [Cost Estimation](#14-cost-estimation)
15. [Our Live Configuration Reference](#15-our-live-configuration-reference)
16. [Troubleshooting](#16-troubleshooting)

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
│  │  (Linux,     │                       │  (vnet-zqopjmgp)  │   │
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
│  │  Zones            │  privatelink.redis.cache.windows.net    │
│  └──────────────────┘                                          │
└─────────────────────────────────────────────────────────────────┘
```

**Key Design Principles:**
- All services are in the **same region** (Canada Central) for low latency
- PostgreSQL and Redis are accessed via **private networking** (no public internet)
- App Service connects to backend services through **VNet Integration**
- CI/CD via **GitHub Actions** — push to `main` triggers automatic deployment

---

## 2. Prerequisites

Before you start, make sure you have:

| Requirement | How to Get It |
|-------------|---------------|
| **Azure Account** | Sign up at [azure.microsoft.com](https://azure.microsoft.com/free/) — free tier available |
| **Azure CLI** | Install: [docs.microsoft.com/cli/azure/install](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) |
| **GitHub Account** | [github.com](https://github.com/) |
| **Git** | [git-scm.com](https://git-scm.com/downloads) |
| **Python 3.10+** | [python.org](https://www.python.org/downloads/) |

**Login to Azure CLI:**

```bash
az login
```

This opens a browser window. Sign in with your Azure account. After login, verify:

```bash
az account show --query "{Name:name, SubscriptionId:id, State:state}" -o table
```

Expected output:

```
Name                  SubscriptionId                        State
--------------------  ------------------------------------  -------
Your Subscription     xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx  Enabled
```

---

## 3. Step 1 — Create a Resource Group

A **Resource Group** is a logical container for all your Azure resources. Put everything in one group so you can manage and delete them together.

### Azure Portal

1. Go to [portal.azure.com](https://portal.azure.com)
2. Click **"Create a resource"** (top left, or the `+` icon)
3. Search for **"Resource group"** → Click **Create**
4. Fill in:
   - **Subscription:** Select your subscription
   - **Resource group name:** `my-portfolio-rg` (or any name you like)
   - **Region:** `Canada Central` (choose a region close to your users)
5. Click **"Review + create"** → **"Create"**

### Azure CLI (Alternative)

```bash
az group create \
  --name my-portfolio-rg \
  --location canadacentral
```

### What You Should See

```json
{
  "id": "/subscriptions/.../resourceGroups/my-portfolio-rg",
  "location": "canadacentral",
  "name": "my-portfolio-rg",
  "properties": {
    "provisioningState": "Succeeded"
  }
}
```

> **Tip:** Choose a region that has all the services you need. `canadacentral`, `eastus`, and `westeurope` are popular choices with full service availability.

---

## 4. Step 2 — Create a Virtual Network (VNet)

A Virtual Network provides **private, secure communication** between your Azure services. Your App Service, PostgreSQL, and Redis will communicate through this VNet instead of the public internet.

### Azure Portal

1. Search for **"Virtual Network"** → Click **Create**
2. **Basics** tab:
   - **Resource group:** `my-portfolio-rg`
   - **Name:** `my-portfolio-vnet`
   - **Region:** `Canada Central` (must match your resource group)
3. **IP Addresses** tab:
   - **Address space:** `10.0.0.0/16` (default, gives you 65,536 IPs)
   - Add three subnets:

   | Subnet Name | Address Range | Purpose |
   |-------------|---------------|---------|
   | `webapp-subnet` | `10.0.1.0/24` | App Service VNet Integration |
   | `postgres-subnet` | `10.0.2.0/24` | PostgreSQL Flexible Server |
   | `cache-subnet` | `10.0.3.0/24` | Redis Private Endpoint |

4. Click **"Review + create"** → **"Create"**

### Azure CLI (Alternative)

```bash
# Create VNet
az network vnet create \
  --resource-group my-portfolio-rg \
  --name my-portfolio-vnet \
  --address-prefix 10.0.0.0/16 \
  --location canadacentral

# Create subnets
az network vnet subnet create \
  --resource-group my-portfolio-rg \
  --vnet-name my-portfolio-vnet \
  --name webapp-subnet \
  --address-prefixes 10.0.1.0/24 \
  --delegations Microsoft.Web/serverFarms

az network vnet subnet create \
  --resource-group my-portfolio-rg \
  --vnet-name my-portfolio-vnet \
  --name postgres-subnet \
  --address-prefixes 10.0.2.0/24 \
  --delegations Microsoft.DBforPostgreSQL/flexibleServers

az network vnet subnet create \
  --resource-group my-portfolio-rg \
  --vnet-name my-portfolio-vnet \
  --name cache-subnet \
  --address-prefixes 10.0.3.0/24
```

> **Important:** The `webapp-subnet` must be delegated to `Microsoft.Web/serverFarms` and the `postgres-subnet` to `Microsoft.DBforPostgreSQL/flexibleServers`. Delegations ensure the subnet is reserved for that specific service.

---

## 5. Step 3 — Create Azure PostgreSQL Flexible Server

PostgreSQL stores all persistent data: visitors, analytics, blog posts, projects.

### Azure Portal

1. Search for **"Azure Database for PostgreSQL Flexible Server"** → Click **Create**
2. **Basics** tab:
   - **Resource group:** `my-portfolio-rg`
   - **Server name:** `my-portfolio-db` (must be globally unique)
   - **Region:** `Canada Central`
   - **PostgreSQL version:** `14` (stable and well-tested)
   - **Workload type:** `Development` (cheapest for personal projects)
   - **Compute + storage:**
     - **Compute tier:** `Burstable`
     - **Compute size:** `Standard_B1ms` (1 vCore, 2 GB RAM — cheapest option)
     - **Storage:** `32 GB` (minimum, can scale up later)
   - **Admin username:** `pgadmin` (or any username)
   - **Password:** Choose a strong password, **save it!**
3. **Networking** tab:
   - **Connectivity method:** `Private access (VNet Integration)`
   - **Virtual network:** `my-portfolio-vnet`
   - **Subnet:** `postgres-subnet`
   - **Private DNS zone:** Create new → `privatelink.postgres.database.azure.com`
4. Click **"Review + create"** → **"Create"**

   ⏱ This takes **5-10 minutes** to provision.

### Azure CLI (Alternative)

```bash
az postgres flexible-server create \
  --resource-group my-portfolio-rg \
  --name my-portfolio-db \
  --location canadacentral \
  --admin-user pgadmin \
  --admin-password "YourStrongPassword123!" \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --version 14 \
  --storage-size 32 \
  --vnet my-portfolio-vnet \
  --subnet postgres-subnet \
  --private-dns-zone privatelink.postgres.database.azure.com
```

### Create the Application Database

After the server is created, create a database for the app:

```bash
az postgres flexible-server db create \
  --resource-group my-portfolio-rg \
  --server-name my-portfolio-db \
  --database-name portfolio
```

### Verify Connection String Format

Your connection string will look like this:

```
host=my-portfolio-db.postgres.database.azure.com dbname=portfolio port=5432 
user=pgadmin password=YourStrongPassword123! sslmode=require
```

> **Security Note:** The server is only accessible from within the VNet. No public IP is exposed, which is more secure than allowing public access.

> **Cost Tip:** `Standard_B1ms` (Burstable) costs ~$12-15/month. For production, `Standard_D2s_v3` (General Purpose) costs ~$125/month but is much more powerful.

---

## 6. Step 4 — Create Azure Cache for Redis

Redis caches analytics stats and blog posts to reduce database queries and improve performance.

### Azure Portal

1. Search for **"Azure Cache for Redis"** → Click **Create**
2. **Basics** tab:
   - **Resource group:** `my-portfolio-rg`
   - **DNS name:** `my-portfolio-cache` (must be globally unique)
   - **Location:** `Canada Central`
   - **Cache SKU:** `Basic`
   - **Cache size:** `C0 (250 MB)` — cheapest option, perfect for caching
3. **Networking** tab:
   - **Connectivity method:** `Private Endpoint`
   - Click **"Add a private endpoint"**:
     - **Name:** `my-portfolio-cache-pe`
     - **Virtual network:** `my-portfolio-vnet`
     - **Subnet:** `cache-subnet`
     - **Private DNS zone:** `privatelink.redis.cache.windows.net`
4. **Advanced** tab:
   - **Non-SSL port:** `Disabled` (use SSL only for security)
   - **Minimum TLS version:** `1.2`
5. Click **"Review + create"** → **"Create"**

   ⏱ This takes **15-20 minutes** to provision.

### Azure CLI (Alternative)

```bash
# Create Redis Cache
az redis create \
  --resource-group my-portfolio-rg \
  --name my-portfolio-cache \
  --location canadacentral \
  --sku Basic \
  --vm-size c0 \
  --minimum-tls-version 1.2

# Create Private Endpoint for Redis
az network private-endpoint create \
  --resource-group my-portfolio-rg \
  --name my-portfolio-cache-pe \
  --vnet-name my-portfolio-vnet \
  --subnet cache-subnet \
  --private-connection-resource-id $(az redis show --resource-group my-portfolio-rg --name my-portfolio-cache --query id -o tsv) \
  --group-id redisCache \
  --connection-name my-portfolio-cache-connection
```

### Get Redis Connection String

After Redis is created, get the access key:

```bash
az redis list-keys \
  --resource-group my-portfolio-rg \
  --name my-portfolio-cache
```

Your connection string format:

```
my-portfolio-cache.redis.cache.windows.net:6380,password=YourAccessKey,ssl=True,abortConnect=False
```

> **Cost Note:** Basic C0 costs ~$16/month. There is no free tier for Azure Redis.

---

## 7. Step 5 — Create an App Service Plan

The App Service Plan defines the compute resources (CPU, RAM) for your web app.

### Azure Portal

1. Search for **"App Service Plan"** → Click **Create**
2. Fill in:
   - **Resource group:** `my-portfolio-rg`
   - **Name:** `my-portfolio-plan`
   - **Operating System:** `Linux`
   - **Region:** `Canada Central`
   - **Pricing tier:** `Basic B1` (1 vCore, 1.75 GB RAM, supports VNet integration)
3. Click **"Review + create"** → **"Create"**

### Azure CLI (Alternative)

```bash
az appservice plan create \
  --resource-group my-portfolio-rg \
  --name my-portfolio-plan \
  --is-linux \
  --sku B1 \
  --location canadacentral
```

> **Pricing Tiers Comparison:**
>
> | Tier | vCPU | RAM | VNet | Custom Domain | Price/Month |
> |------|------|-----|------|---------------|-------------|
> | Free F1 | Shared | 1 GB | ❌ | ❌ | $0 |
> | Basic B1 | 1 | 1.75 GB | ✅ | ✅ | ~$13 |
> | Standard S1 | 1 | 1.75 GB | ✅ | ✅ + Slots | ~$70 |
> | Premium P1v3 | 2 | 8 GB | ✅ | ✅ + Slots + Scale | ~$130 |
>
> **Recommendation:** Use **Basic B1** for personal projects. It supports VNet integration which is needed for private PostgreSQL and Redis access.

---

## 8. Step 6 — Create the Web App (App Service)

This is the web application that runs your Flask code.

### Azure Portal

1. Search for **"App Service"** → Click **Create** → **Web App**
2. **Basics** tab:
   - **Resource group:** `my-portfolio-rg`
   - **Name:** `my-portfolio-app` (this becomes `my-portfolio-app.azurewebsites.net`)
   - **Publish:** `Code`
   - **Runtime stack:** `Python 3.12` (or latest stable)
   - **Operating system:** `Linux`
   - **Region:** `Canada Central`
   - **App Service Plan:** `my-portfolio-plan` (the one you created in Step 5)
3. **Deployment** tab:
   - Enable **GitHub Actions** continuous deployment (we'll configure in Step 8)
4. **Networking** tab:
   - **Enable public access:** `On` (users need to reach your website)
   - **Enable network injection:** `On`
   - **Virtual network:** `my-portfolio-vnet`
   - **Subnet:** `webapp-subnet`
5. Click **"Review + create"** → **"Create"**

### Azure CLI (Alternative)

```bash
# Create the Web App
az webapp create \
  --resource-group my-portfolio-rg \
  --plan my-portfolio-plan \
  --name my-portfolio-app \
  --runtime "PYTHON:3.12"

# Enable VNet Integration
az webapp vnet-integration add \
  --resource-group my-portfolio-rg \
  --name my-portfolio-app \
  --vnet my-portfolio-vnet \
  --subnet webapp-subnet
```

### Configure the Startup Command

Flask needs a production WSGI server. We use **Gunicorn**:

```bash
az webapp config set \
  --resource-group my-portfolio-rg \
  --name my-portfolio-app \
  --startup-file "gunicorn --bind=0.0.0.0:8000 --timeout 600 app:app"
```

This tells Azure to:
- Use `gunicorn` (a production-ready Python HTTP server)
- Bind to port `8000` (Azure's default for Python apps)
- Set timeout to `600` seconds (needed for long DB operations on first start)
- Run the Flask `app` object from `app.py`

### Enable HTTPS Only

```bash
az webapp update \
  --resource-group my-portfolio-rg \
  --name my-portfolio-app \
  --https-only true
```

### Enable Build During Deployment

```bash
az webapp config appsettings set \
  --resource-group my-portfolio-rg \
  --name my-portfolio-app \
  --settings SCM_DO_BUILD_DURING_DEPLOYMENT=true
```

This tells Azure to run `pip install -r requirements.txt` automatically during deployment.

---

## 9. Step 7 — Configure App Settings & Connection Strings

Your Flask app needs environment variables for database connections, email, and more.

### Required App Settings

| Setting | Value | Purpose |
|---------|-------|---------|
| `OWNER_EMAIL` | `your@email.com` | Receives contact form notifications |
| `SMTP_SERVER` | `smtp.gmail.com` | Gmail SMTP server |
| `SMTP_PORT` | `587` | Gmail SMTP port (TLS) |
| `SMTP_USER` | `your@gmail.com` | Gmail account for sending |
| `SMTP_PASS` | `xxxx xxxx xxxx xxxx` | Gmail App Password (NOT your Gmail password) |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` | Auto-install Python packages |

### Azure Portal

1. Go to your **App Service** → **Settings** → **Environment variables**
2. Under **App settings**, click **"+ Add"** for each setting:

   ```
   Name: OWNER_EMAIL         Value: your@email.com
   Name: SMTP_SERVER          Value: smtp.gmail.com
   Name: SMTP_PORT            Value: 587
   Name: SMTP_USER            Value: your@gmail.com
   Name: SMTP_PASS            Value: your-app-password
   ```

3. Under **Connection strings**, click **"+ Add"**:

   | Name | Value | Type |
   |------|-------|------|
   | `AZURE_POSTGRESQL_CONNECTIONSTRING` | `host=my-portfolio-db.postgres.database.azure.com dbname=portfolio port=5432 user=pgadmin password=YourPassword sslmode=require` | `PostgreSQL` |
   | `azure_redis_cache` | `my-portfolio-cache.redis.cache.windows.net:6380,password=YourRedisKey,ssl=True,abortConnect=False` | `Custom` |

4. Click **"Apply"** → **"Confirm"**

### Azure CLI (Alternative)

```bash
# Set App Settings
az webapp config appsettings set \
  --resource-group my-portfolio-rg \
  --name my-portfolio-app \
  --settings \
    OWNER_EMAIL="your@email.com" \
    SMTP_SERVER="smtp.gmail.com" \
    SMTP_PORT="587" \
    SMTP_USER="your@gmail.com" \
    SMTP_PASS="your-app-password" \
    SCM_DO_BUILD_DURING_DEPLOYMENT="true"

# Set Connection Strings
az webapp config connection-string set \
  --resource-group my-portfolio-rg \
  --name my-portfolio-app \
  --connection-string-type PostgreSQL \
  --settings AZURE_POSTGRESQL_CONNECTIONSTRING="host=my-portfolio-db.postgres.database.azure.com dbname=portfolio port=5432 user=pgadmin password=YourPassword sslmode=require"

az webapp config connection-string set \
  --resource-group my-portfolio-rg \
  --name my-portfolio-app \
  --connection-string-type Custom \
  --settings azure_redis_cache="my-portfolio-cache.redis.cache.windows.net:6380,password=YourRedisKey,ssl=True,abortConnect=False"
```

### How to Get a Gmail App Password

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Enable **2-Step Verification** if not already on
3. Search for **"App passwords"** in the security page
4. Create a new app password:
   - App: `Mail`
   - Device: `Other` → Name it `Azure Portfolio`
5. Copy the 16-character password (format: `xxxx xxxx xxxx xxxx`)
6. Use this as the `SMTP_PASS` value

> **Security Warning:** Never commit passwords or connection strings to Git. Always use App Settings/Environment Variables.

---

## 10. Step 8 — Set Up GitHub Actions CI/CD

Continuous deployment means every `git push` to `main` automatically deploys to Azure.

### Step 8a — Get Publish Profile

1. Go to your **App Service** → **Overview** → Click **"Download publish profile"**
2. This downloads an XML file containing deployment credentials

### Step 8b — Add GitHub Secret

1. Go to your GitHub repository → **Settings** → **Secrets and variables** → **Actions**
2. Click **"New repository secret"**
   - **Name:** `AZUREAPPSERVICE_PUBLISHPROFILE`
   - **Value:** Paste the **entire contents** of the publish profile XML file
3. Click **"Add secret"**

### Step 8c — Create GitHub Actions Workflow

Create the file `.github/workflows/main_aimeelan.yml` in your repository:

```yaml
name: Build and deploy Python app to Azure Web App

on:
  push:
    branches:
      - main
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python version
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Create and start virtual environment
        run: |
          python -m venv venv
          source venv/bin/activate

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Zip artifact for deployment
        run: zip release.zip ./* -r

      - name: Upload artifact for deployment jobs
        uses: actions/upload-artifact@v4
        with:
          name: python-app
          path: |
            release.zip
            !venv/

  deploy:
    runs-on: ubuntu-latest
    needs: build
    environment:
      name: 'Production'
      url: ${{ steps.deploy-to-webapp.outputs.webapp-url }}

    steps:
      - name: Download artifact from build job
        uses: actions/download-artifact@v4
        with:
          name: python-app

      - name: Unzip artifact for deployment
        run: unzip release.zip

      - name: 'Deploy to Azure Web App'
        uses: azure/webapps-deploy@v3
        id: deploy-to-webapp
        with:
          app-name: 'my-portfolio-app'
          slot-name: 'Production'
          publish-profile: ${{ secrets.AZUREAPPSERVICE_PUBLISHPROFILE }}
```

### Step 8d — Push and Watch

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

## 11. Step 9 — Configure Networking & Private Endpoints

Your App Service needs to reach PostgreSQL and Redis through the VNet. Here's how the network connectivity works:

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
       │ VNet Integration (private traffic)
       ▼
┌──────────────────┐
│  Virtual Network │
│  10.0.0.0/16     │
│                  │
│  ┌────────────┐  │
│  │ postgres-  │  │    Private DNS:
│  │ subnet     │──┼──► my-portfolio-db.postgres.database.azure.com
│  │ 10.0.2.0/24│  │    → resolves to private IP (e.g., 10.0.2.4)
│  └────────────┘  │
│                  │
│  ┌────────────┐  │    Private Endpoint:
│  │ cache-     │  │    my-portfolio-cache.redis.cache.windows.net
│  │ subnet     │──┼──► → resolves to private IP (e.g., 10.0.3.4)
│  │ 10.0.3.0/24│  │
│  └────────────┘  │
└──────────────────┘
```

### Verify VNet Integration

If you set up VNet integration during App Service creation, it's already done. To verify:

```bash
az webapp vnet-integration list \
  --name my-portfolio-app \
  --resource-group my-portfolio-rg \
  -o table
```

Expected output:

```
Location        Name            ResourceGroup
--------------  --------------  ---------------
Canada Central  webapp-subnet   my-portfolio-rg
```

### Verify Private DNS Resolution

From the App Service console (Portal → App Service → Development Tools → Console), test DNS:

```bash
nslookup my-portfolio-db.postgres.database.azure.com
```

It should resolve to a **private IP** (10.x.x.x), not a public IP.

---

## 12. Step 10 — Verify Deployment

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

## 13. Step 11 — Set Up Monitoring & Logs

### Enable HTTP Logging

```bash
az webapp config appsettings set \
  --resource-group my-portfolio-rg \
  --name my-portfolio-app \
  --settings WEBSITE_HTTPLOGGING_RETENTION_DAYS=7
```

### Enable Diagnostic Logging

In the Azure Portal:

1. Go to your **App Service** → **Monitoring** → **Diagnostic settings**
2. Click **"+ Add diagnostic setting"**
3. Check:
   - ✅ **AppServiceHTTPLogs**
   - ✅ **AppServiceConsoleLogs**
   - ✅ **AppServiceAppLogs**
4. Send to: **Log Analytics workspace** (create one if needed)

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

## 14. Cost Estimation

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

## 15. Our Live Configuration Reference

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

## 16. Troubleshooting

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
- [ ] Created Virtual Network with 3 subnets
- [ ] Created PostgreSQL Flexible Server (VNet integrated)
- [ ] Created application database
- [ ] Created Azure Cache for Redis with Private Endpoint
- [ ] Created App Service Plan (Linux, Basic B1)
- [ ] Created Web App (Python runtime)
- [ ] Configured startup command (gunicorn)
- [ ] Enabled HTTPS only
- [ ] Added App Settings (email, SMTP)
- [ ] Added Connection Strings (PostgreSQL, Redis)
- [ ] Set up GitHub Actions workflow
- [ ] Added publish profile as GitHub secret
- [ ] Pushed code and verified deployment
- [ ] Tested full user flow (verify → blog → admin)
- [ ] Enabled logging and monitoring

**Congratulations!** Your Flask portfolio website is now running on Azure with enterprise-grade infrastructure. 🎉
