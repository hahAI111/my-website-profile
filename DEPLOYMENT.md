# CI/CD 部署流水线 — 从代码到上线全流程

本项目使用 **GitHub Actions** 实现自动化 CI/CD 部署。
每次 `git push` 到 `main` 分支，代码会自动构建并部署到 Azure App Service。

---

## 目录

- [架构总览](#架构总览)
- [三大组件及其角色](#三大组件及其角色)
- [完整部署流程](#完整部署流程)
  - [Step 1：本地 → GitHub](#step-1本地--github)
  - [Step 2：GitHub Actions 自动触发](#step-2github-actions-自动触发)
  - [Step 3：Build 阶段](#step-3build-阶段)
  - [Step 4：Deploy 阶段](#step-4deploy-阶段)
  - [Step 5：Azure App Service 接管](#step-5azure-app-service-接管)
- [Workflow 配置文件详解](#workflow-配置文件详解)
- [Azure App Service 运行机制](#azure-app-service-运行机制)
  - [Oryx 构建引擎](#oryx-构建引擎)
  - [gunicorn 启动](#gunicorn-启动)
  - [环境变量](#环境变量)
- [部署状态查看](#部署状态查看)
  - [GitHub Actions 页面](#github-actions-页面)
  - [Azure 门户](#azure-门户)
- [常见部署问题及解决方案](#常见部署问题及解决方案)
- [手动部署方法](#手动部署方法)
- [FAQ](#faq)

---

## 架构总览

```
┌─────────────┐      git push      ┌─────────────┐     OneDeploy     ┌──────────────────┐
│             │ ──────────────────> │             │ ─────────────────> │                  │
│  本地电脑    │                     │   GitHub    │                    │  Azure App       │
│  (VS Code)  │                     │   (代码仓库) │                    │  Service         │
│             │ <── git pull ────── │             │                    │  (运行网站)       │
└─────────────┘                     └─────────────┘                    └──────────────────┘
      │                                   │                                    │
  编写代码                          GitHub Actions                        Flask + gunicorn
  git add/commit                   自动 build + deploy                  处理用户请求 
                                                                       
                                                                  https://aimeelan.azurewebsites.net
```

## 三大组件及其角色

| 组件 | 位置 | 作用 | 类比 |
|---|---|---|---|
| **本地电脑 (VS Code)** | 你的电脑 | 编写和测试代码 | 厨师的厨房 |
| **GitHub** | github.com/hahAI111/aimeewebpage | 存储代码 + 自动化部署中转 | 快递公司（接货+送货） |
| **Azure App Service** | aimeelan.azurewebsites.net | 运行网站，对外提供服务 | 餐厅（客人来这里访问） |

**核心逻辑**：你只需要 `git push`，后面的一切都是自动的。

---

## 完整部署流程

### Step 1：本地 → GitHub

```bash
# 修改代码后
git add -A                    # 暂存所有改动
git commit -m "描述这次改了什么"  # 提交到本地仓库
git push origin main          # 推送到 GitHub 的 main 分支
```

这一步做的事情：
- 把你电脑上的代码变更上传到 GitHub 仓库
- GitHub 收到 push 后，检查是否有配置好的 Actions workflow

### Step 2：GitHub Actions 自动触发

GitHub 检测到 `main` 分支有新的 push，自动执行 `.github/workflows/main_aimeelan.yml`。

触发条件（定义在 workflow 文件中）：
```yaml
on:
  push:
    branches:
      - main          # main 分支有 push 时自动触发
  workflow_dispatch:   # 也可以在 GitHub 页面手动触发
```

### Step 3：Build 阶段

在 GitHub 提供的 **ubuntu-latest** 虚拟机上执行：

```
1. actions/checkout@v4        → 拉取你的最新代码
2. actions/setup-python@v5    → 安装 Python 3.14
3. pip install -r requirements.txt → 安装依赖（验证能否正常安装）
4. actions/upload-artifact@v4  → 把代码打包成 artifact（排除虚拟环境）
```

**目的**：提前验证代码能否正常安装依赖，有问题在这一步就会失败，不会影响线上。

### Step 4：Deploy 阶段

```
1. actions/download-artifact@v4  → 下载 build 阶段的打包文件
2. azure/login@v2               → 用密钥登录 Azure（Service Principal）
3. azure/webapps-deploy@v3       → 把代码包通过 OneDeploy API 上传到 Azure
```

**认证方式**：使用 OIDC（OpenID Connect）联合凭证，GitHub 和 Azure 之间建立了信任关系。
密钥存储在 GitHub 仓库的 Secrets 中：
- `AZUREAPPSERVICE_CLIENTID_xxx`
- `AZUREAPPSERVICE_TENANTID_xxx`
- `AZUREAPPSERVICE_SUBSCRIPTIONID_xxx`

### Step 5：Azure App Service 接管

Azure 收到代码包后：

```
1. Oryx 构建引擎检测到 requirements.txt → 识别为 Python 项目
2. 创建虚拟环境，pip install -r requirements.txt
3. 执行启动命令：gunicorn --bind=0.0.0.0:8000 --timeout 600 app:app
4. Flask 应用启动，init_db() 运行
5. 网站开始对外服务
```

**整个流程耗时**：通常 2-4 分钟（build ~16s + deploy ~1-2min + 启动 ~30s）

---

## Workflow 配置文件详解

文件路径：`.github/workflows/main_aimeelan.yml`

```yaml
name: Build and deploy Python app to Azure Web App - aimeelan

# ── 触发条件 ──
on:
  push:
    branches: [ main ]         # push 到 main 时自动触发
  workflow_dispatch:            # 支持手动触发

jobs:
  # ── 构建阶段 ──
  build:
    runs-on: ubuntu-latest      # 在 GitHub 提供的 Ubuntu 虚拟机上运行
    permissions:
      contents: read            # 需要读取仓库代码

    steps:
      - uses: actions/checkout@v4           # 拉取代码

      - name: Set up Python version
        uses: actions/setup-python@v5
        with:
          python-version: '3.14'            # 与 Azure App Service 上的版本一致

      - name: Create and Start virtual environment and Install dependencies
        run: |
          python -m venv antenv             # 创建虚拟环境
          source antenv/bin/activate        # 激活
          pip install -r requirements.txt   # 安装依赖（预检）

      - name: Upload artifact for deployment jobs
        uses: actions/upload-artifact@v4
        with:
          name: python-app
          path: |
            .
            !antenv/                        # 排除虚拟环境（Azure 会自己安装）

  # ── 部署阶段 ──
  deploy:
    runs-on: ubuntu-latest
    needs: build                 # 依赖 build 成功后才执行
    permissions:
      id-token: write            # OIDC 认证需要
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
          app-name: 'aimeelan'              # App Service 名称
          slot-name: 'Production'           # 部署槽（生产）
```

---

## Azure App Service 运行机制

### Oryx 构建引擎

Azure 收到代码后，**Oryx** 负责构建：

```
检测 requirements.txt ─→ 识别为 Python 项目
            │
            ├── 创建 /antenv 虚拟环境
            ├── pip install -r requirements.txt
            │     ├── flask
            │     ├── gunicorn
            │     ├── psycopg2-binary
            │     ├── redis
            │     ├── requests
            │     └── bcrypt
            └── 构建完成
```

这个过程由环境变量 `SCM_DO_BUILD_DURING_DEPLOYMENT=true` 控制。

### gunicorn 启动

Azure App Service → **配置 → 常规设置 → 启动命令**：

```bash
gunicorn --bind=0.0.0.0:8000 --timeout 600 app:app
```

| 参数 | 含义 |
|---|---|
| `--bind=0.0.0.0:8000` | 监听所有网络接口的 8000 端口 |
| `--timeout 600` | 请求超时 600 秒（给长查询留余地） |
| `app:app` | 从 `app.py` 文件导入 `app` 对象（Flask 实例） |

gunicorn 是生产级 WSGI 服务器，替代 Flask 自带的开发服务器。

### 环境变量

在 Azure Portal → `aimeelan` → **配置 → 应用程序设置** 中配置：

| 变量 | 用途 | 配置位置 |
|---|---|---|
| `AZURE_POSTGRESQL_CONNECTIONSTRING` | PostgreSQL 连接字符串 | Service Connector 或手动 |
| `AZURE_REDIS_CONNECTIONSTRING` | Redis 连接字符串 | Service Connector 或手动 |
| `OWNER_EMAIL` | 接收通知的邮箱 | 手动 |
| `SMTP_SERVER` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` | 邮件发送配置 | 手动 |
| `ADMIN_USER` / `ADMIN_PASS_HASH` | Admin 登录凭证 | 手动 |
| `GITHUB_USERNAME` / `GITHUB_TOKEN` | GitHub API 同步用 | 手动 |
| `GITHUB_SYNC_INTERVAL` | 自动同步间隔（秒，默认 21600） | 手动（可选） |
| `SECRET_KEY` | Flask session 密钥 | 手动（可选） |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | 让 Oryx 在部署时构建 | Azure 自动设置 |

**这些变量不存在于代码中**，只在 Azure 运行环境中生效，保证密码安全。

---

## 部署状态查看

### GitHub Actions 页面

**地址**：`https://github.com/hahAI111/aimeewebpage/actions`

每次 push 会产生一个 workflow run，可以看到：
- ✅ 绿色 = build/deploy 成功
- ❌ 红色 = 失败（点击查看详细日志）
- 🟡 黄色 = 正在进行

### Azure 门户

**Azure Portal → `aimeelan` → 部署中心**：
- 可以看到所有部署历史
- 每次部署的状态、时间、提交信息

**Azure Portal → `aimeelan` → 日志流 (Log Stream)**：
- 实时查看应用启动日志
- 可以看到 `Redis connected successfully`、`GitHub projects seeded` 等输出

---

## 常见部署问题及解决方案

### 1. 409 Conflict（部署冲突）

**原因**：上一次部署还在进行中，新的部署请求被拒绝。  
**常见场景**：短时间内连续 push 多次。

**解决**：
```bash
# 重启 App Service 清除部署锁
az webapp restart --name aimeelan --resource-group aimee-test-env

# 等 10 秒后重新触发部署
git commit --allow-empty -m "Retry deploy"
git push origin main
```

**预防**：多次改动合并到一个 commit 再 push，避免连续触发多次部署。

### 2. Build 失败（pip install 错误）

**原因**：requirements.txt 中的某个包无法安装。  
**常见**：`bcrypt` 需要编译 C 扩展，某些环境可能缺少编译工具。

**排查**：
1. 点击 GitHub Actions 页面的红色 build 步骤
2. 查看详细日志，找到 `pip install` 失败的具体包
3. 修复 requirements.txt（换包或锁定版本）

### 3. Deploy 成功但网站 503

**原因**：代码部署成功但 Flask 启动失败。  
**常见**：
- import 错误（某个包没装上）
- `init_db()` 连接数据库失败
- 语法错误

**排查**：
```bash
# 查看 Azure 应用日志
az webapp log tail --name aimeelan --resource-group aimee-test-env
```

或 Azure Portal → `aimeelan` → **日志流**

### 4. 部署成功但内容没更新

**原因**：浏览器缓存了旧的 HTML/CSS/JS。

**解决**：
- 浏览器硬刷新：`Ctrl + Shift + R`
- 或清除浏览器缓存

### 5. Git push 被拒绝

**原因**：远程有你本地没有的提交。

**解决**：
```bash
git pull origin main --rebase   # 拉取远程变更
git push origin main             # 再推送
```

---

## 手动部署方法

如果 GitHub Actions 持续失败，可以绕过它直接从本地部署：

### 方法 1：Azure CLI 部署

```bash
# 打包代码（排除不需要的文件）
cd C:\Users\jingwang1\my-website
Compress-Archive -Path * -DestinationPath deploy.zip -Force

# 直接部署到 Azure
az webapp deploy --resource-group aimee-test-env --name aimeelan --src-path deploy.zip --type zip
```

### 方法 2：在 GitHub Actions 页面手动触发

GitHub → 仓库 → Actions → 选择 workflow → **Run workflow** 按钮  
（workflow 配置了 `workflow_dispatch`，支持手动触发）

### 方法 3：重新运行失败的 workflow

GitHub → Actions → 点击失败的 run → **Re-run all jobs**

---

## FAQ

**Q：我必须用 GitHub 才能部署吗？**  
A：不是。GitHub Actions 只是自动化工具。你也可以用 Azure CLI 从本地直接部署（见"手动部署"）。
但 GitHub Actions 最方便——push 一下就自动部署，不用记任何命令。

**Q：push 到其他分支（不是 main）会触发部署吗？**  
A：不会。workflow 只监听 `main` 分支。你可以在其他分支开发，测试好了再合并到 main。

**Q：GitHub 上的 Secrets 是什么？**  
A：是 Azure 的认证凭证，存储在 GitHub 仓库的 Settings → Secrets 中。
GitHub Actions 用这些 Secrets 登录你的 Azure 账号来执行部署。
它们是加密存储的，任何人（包括你）都看不到明文。

**Q：修改 Azure 环境变量需要重新部署吗？**  
A：不需要。Azure 修改环境变量后会自动重启 App Service，新的值立即生效。

**Q：部署需要多久？**  
A：通常 2-4 分钟。Build ~16 秒 + Deploy ~1-2 分钟 + Azure 构建+启动 ~30-60 秒。

**Q：可以回滚到之前的版本吗？**  
A：可以。方法 1：`git revert` 回退代码再 push。方法 2：Azure Portal → 部署中心 → 选择之前的部署 → 重新部署。
