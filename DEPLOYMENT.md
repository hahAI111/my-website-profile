# CI/CD Deployment Pipeline — From Code to Production

This project uses **GitHub Actions** for automated CI/CD deployment.
Every `git push` to the `main` branch automatically builds and deploys the code to Azure App Service.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Three Components & Their Roles](#three-components--their-roles)
- [Complete Deployment Flow](#complete-deployment-flow)
  - [Step 1: Local → GitHub](#step-1-local--github)
  - [Step 2: GitHub Actions Auto-Trigger](#step-2-github-actions-auto-trigger)
  - [Step 3: Build Stage](#step-3-build-stage)
  - [Step 4: Deploy Stage](#step-4-deploy-stage)
  - [Step 5: Azure App Service Takes Over](#step-5-azure-app-service-takes-over)
- [Workflow Configuration Explained](#workflow-configuration-explained)
- [Azure App Service Runtime](#azure-app-service-runtime)
  - [Oryx Build Engine](#oryx-build-engine)
  - [gunicorn Startup](#gunicorn-startup)
  - [Environment Variables](#environment-variables)
- [Monitoring Deployment Status](#monitoring-deployment-status)
  - [GitHub Actions Page](#github-actions-page)
  - [Azure Portal](#azure-portal)
- [Common Deployment Issues & Solutions](#common-deployment-issues--solutions)
- [Manual Deployment Methods](#manual-deployment-methods)
- [FAQ](#faq)

---

## Architecture Overview

```
┌─────────────┐      git push      ┌─────────────┐     OneDeploy     ┌──────────────────┐
│             │ ──────────────────> │             │ ─────────────────> │                  │
│  Local PC   │                     │   GitHub    │                    │  Azure App       │
│  (VS Code)  │                     │  (Code Repo)│                    │  Service         │
│             │ <── git pull ────── │             │                    │  (Runs website)  │
└─────────────┘                     └─────────────┘                    └──────────────────┘
      │                                   │                                    │
  Write code                        GitHub Actions                      Flask + gunicorn
  git add/commit                   auto build + deploy                 handles user requests
                                                                       
                                                                  https://aimeelan.azurewebsites.net
```

## Three Components & Their Roles

| Component | Location | Purpose | Analogy |
|---|---|---|---|
| **Local PC (VS Code)** | Your computer | Write and test code | Chef's kitchen |
| **GitHub** | github.com/hahAI111/aimeewebpage | Store code + CI/CD relay | Delivery company (pick up + deliver) |
| **Azure App Service** | aimeelan.azurewebsites.net | Run the website, serve users | Restaurant (where customers visit) |

**Core logic**: You only need `git push` — everything after that is automated.

---

## Complete Deployment Flow

### Step 1: Local → GitHub

```bash
# After modifying code
git add -A                        # Stage all changes
git commit -m "describe changes"  # Commit to local repository
git push origin main              # Push to GitHub's main branch
```

What this step does:
- Uploads your local code changes to the GitHub repository
- GitHub checks whether there's a configured Actions workflow

### Step 2: GitHub Actions Auto-Trigger

GitHub detects a new push to the `main` branch and automatically executes `.github/workflows/main_aimeelan.yml`.

Trigger conditions (defined in the workflow file):
```yaml
on:
  push:
    branches:
      - main          # Auto-trigger on push to main branch
  workflow_dispatch:   # Also supports manual trigger from GitHub page
```

### Step 3: Build Stage

Runs on a GitHub-provided **ubuntu-latest** virtual machine:

```
1. actions/checkout@v4        → Pull latest code
2. actions/setup-python@v5    → Install Python 3.14
3. pip install -r requirements.txt → Install dependencies (verify they install correctly)
4. actions/upload-artifact@v4  → Package code as artifact (excluding virtual environment)
```

**Purpose**: Pre-validate that code can install dependencies correctly. If there's an issue, it fails here without affecting production.

### Step 4: Deploy Stage

```
1. actions/download-artifact@v4  → Download the packaged artifact from build stage
2. azure/login@v2               → Log in to Azure using credentials (Service Principal)
3. azure/webapps-deploy@v3       → Upload code package to Azure via OneDeploy API
```

**Authentication**: Uses OIDC (OpenID Connect) federated credentials — a trust relationship between GitHub and Azure.
Secrets are stored in the GitHub repository's Secrets:
- `AZUREAPPSERVICE_CLIENTID_xxx`
- `AZUREAPPSERVICE_TENANTID_xxx`
- `AZUREAPPSERVICE_SUBSCRIPTIONID_xxx`

### Step 5: Azure App Service Takes Over

After Azure receives the code package:

```
1. Oryx build engine detects requirements.txt → identifies as Python project
2. Creates virtual environment, pip install -r requirements.txt
3. Executes startup command: gunicorn --bind=0.0.0.0:8000 --timeout 600 app:app
4. Flask application starts, init_db() runs
5. Website begins serving traffic
```

**Total time**: Typically 2–4 minutes (build ~16s + deploy ~1–2min + startup ~30s)

---

## Workflow Configuration Explained

File path: `.github/workflows/main_aimeelan.yml`

```yaml
name: Build and deploy Python app to Azure Web App - aimeelan

# ── Trigger conditions ──
on:
  push:
    branches: [ main ]         # Auto-trigger on push to main
  workflow_dispatch:            # Supports manual trigger

jobs:
  # ── Build stage ──
  build:
    runs-on: ubuntu-latest      # Runs on GitHub-provided Ubuntu VM
    permissions:
      contents: read            # Needs read access to repo code

    steps:
      - uses: actions/checkout@v4           # Pull code

      - name: Set up Python version
        uses: actions/setup-python@v5
        with:
          python-version: '3.14'            # Matches Azure App Service version

      - name: Create and Start virtual environment and Install dependencies
        run: |
          python -m venv antenv             # Create virtual environment
          source antenv/bin/activate        # Activate
          pip install -r requirements.txt   # Install dependencies (pre-check)

      - name: Upload artifact for deployment jobs
        uses: actions/upload-artifact@v4
        with:
          name: python-app
          path: |
            .
            !antenv/                        # Exclude venv (Azure installs its own)

  # ── Deploy stage ──
  deploy:
    runs-on: ubuntu-latest
    needs: build                 # Depends on successful build
    permissions:
      id-token: write            # Required for OIDC authentication
      contents: read

    steps:
      - name: Download artifact from build job
        uses: actions/download-artifact@v4

      - name: Login to Azure
        uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZUREAPPSERVICE_CLIENTID_xxx }}
          tenant-id: ${{ secrets.AZUREAPPSERVICE_TENANTID_xxx }}
          subscription-id: ${{ secrets.AZUREAPPSERVICE_SUBSCRIPTIONID_xxx }}

      - name: Deploy to Azure Web App
        uses: azure/webapps-deploy@v3
        with:
          app-name: 'aimeelan'              # App Service name
          slot-name: 'Production'           # Deployment slot
```

---

## Azure App Service Runtime

### Oryx Build Engine

After Azure receives the code, **Oryx** handles the build:

```
Detects requirements.txt ─→ Identifies as Python project
            │
            ├── Creates /antenv virtual environment
            ├── pip install -r requirements.txt
            │     ├── flask
            │     ├── gunicorn
            │     ├── psycopg2-binary
            │     ├── redis
            │     ├── requests
            │     └── bcrypt
            └── Build complete
```

This process is controlled by the `SCM_DO_BUILD_DURING_DEPLOYMENT=true` environment variable.

### gunicorn Startup

Azure App Service → **Configuration → General settings → Startup Command**:

```bash
gunicorn --bind=0.0.0.0:8000 --timeout 600 app:app
```

| Parameter | Meaning |
|---|---|
| `--bind=0.0.0.0:8000` | Listen on all interfaces, port 8000 |
| `--timeout 600` | Request timeout 600 seconds (gives heavy queries room) |
| `app:app` | Import `app` object from `app.py` (Flask instance) |

gunicorn is a production-grade WSGI server, replacing Flask's built-in development server.

### Environment Variables

Configured in Azure Portal → `aimeelan` → **Configuration → Application settings**:

| Variable | Purpose | Where to Configure |
|---|---|---|
| `AZURE_POSTGRESQL_CONNECTIONSTRING` | PostgreSQL connection string | Service Connector or manual |
| `AZURE_REDIS_CONNECTIONSTRING` | Redis connection string | Service Connector or manual |
| `OWNER_EMAIL` | Email to receive notifications | Manual |
| `SMTP_SERVER` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` | Email sending config | Manual |
| `ADMIN_USER` / `ADMIN_PASS_HASH` | Admin login credentials | Manual |
| `GITHUB_USERNAME` / `GITHUB_TOKEN` | For GitHub API sync | Manual |
| `GITHUB_SYNC_INTERVAL` | Auto-sync interval in seconds (default 21600) | Manual (optional) |
| `SECRET_KEY` | Flask session secret key | Manual (optional) |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | Enables Oryx build during deployment | Azure auto-set |

**These variables do not exist in the codebase** — they only take effect in the Azure runtime environment, keeping passwords secure.

---

## Monitoring Deployment Status

### GitHub Actions Page

**URL**: `https://github.com/hahAI111/aimeewebpage/actions`

Each push creates a workflow run where you can see:
- ✅ Green = build/deploy succeeded
- ❌ Red = failed (click to view detailed logs)
- 🟡 Yellow = in progress

### Azure Portal

**Azure Portal → `aimeelan` → Deployment Center**:
- View all deployment history
- Status, time, and commit info for each deployment

**Azure Portal → `aimeelan` → Log Stream**:
- View real-time application startup logs
- See outputs like `Redis connected successfully`, `GitHub projects seeded`, etc.

---

## Common Deployment Issues & Solutions

### 1. 409 Conflict (Deployment Conflict)

**Cause**: A previous deployment is still in progress; the new deployment request is rejected.  
**Common scenario**: Pushing multiple times in quick succession.

**Solution**:
```bash
# Restart App Service to clear the deployment lock
az webapp restart --name aimeelan --resource-group aimee-test-env

# Wait 10 seconds then re-trigger deployment
git commit --allow-empty -m "Retry deploy"
git push origin main
```

**Prevention**: Batch multiple changes into a single commit before pushing to avoid triggering multiple deployments.

### 2. Build Failure (pip install error)

**Cause**: A package in requirements.txt fails to install.  
**Common**: `bcrypt` requires C extension compilation; some environments may lack build tools.

**Troubleshooting**:
1. Click the red build step on the GitHub Actions page
2. Review detailed logs to find the specific package that failed `pip install`
3. Fix requirements.txt (switch package or pin version)

### 3. Deploy Succeeds but Site Returns 503

**Cause**: Code deployed successfully but Flask fails to start.  
**Common**:
- Import error (a package didn't install properly)
- `init_db()` fails to connect to the database
- Syntax error

**Troubleshooting**:
```bash
# View Azure application logs
az webapp log tail --name aimeelan --resource-group aimee-test-env
```

Or Azure Portal → `aimeelan` → **Log Stream**

### 4. Deploy Succeeds but Content Not Updated

**Cause**: Browser cached old HTML/CSS/JS files.

**Solution**:
- Hard refresh: `Ctrl + Shift + R`
- Or clear browser cache

### 5. Git Push Rejected

**Cause**: Remote has commits you don't have locally.

**Solution**:
```bash
git pull origin main --rebase   # Pull remote changes
git push origin main             # Push again
```

---

## Manual Deployment Methods

If GitHub Actions keeps failing, you can bypass it and deploy directly from local:

### Method 1: Azure CLI Deployment

```bash
# Package code (exclude unnecessary files)
cd C:\Users\jingwang1\my-website
Compress-Archive -Path * -DestinationPath deploy.zip -Force

# Deploy directly to Azure
az webapp deploy --resource-group aimee-test-env --name aimeelan --src-path deploy.zip --type zip
```

### Method 2: Manual Trigger on GitHub Actions Page

GitHub → Repository → Actions → Select workflow → **Run workflow** button  
(The workflow is configured with `workflow_dispatch`, supporting manual triggers)

### Method 3: Re-run Failed Workflow

GitHub → Actions → Click the failed run → **Re-run all jobs**

---

## FAQ

**Q: Do I have to use GitHub to deploy?**  
A: No. GitHub Actions is just an automation tool. You can deploy directly from local using Azure CLI (see "Manual Deployment"). But GitHub Actions is the most convenient — push once and it auto-deploys; no commands to remember.

**Q: Will pushing to other branches (not main) trigger deployment?**  
A: No. The workflow only monitors the `main` branch. You can develop on other branches and merge to main when ready.

**Q: What are the Secrets on GitHub?**  
A: They are Azure authentication credentials stored in the GitHub repo under Settings → Secrets. GitHub Actions uses these Secrets to log into your Azure account for deployment. They are encrypted — no one (including you) can see the plaintext.

**Q: Do I need to redeploy after changing Azure environment variables?**  
A: No. Azure automatically restarts the App Service after changing environment variables; new values take effect immediately.

**Q: How long does deployment take?**  
A: Typically 2–4 minutes. Build ~16 seconds + Deploy ~1–2 minutes + Azure build + startup ~30–60 seconds.

**Q: Can I roll back to a previous version?**  
A: Yes. Method 1: `git revert` the code changes and push again. Method 2: Azure Portal → Deployment Center → select a previous deployment → redeploy.
