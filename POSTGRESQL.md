# PostgreSQL 数据库 — 使用说明与监控指南

本项目使用 **Azure Database for PostgreSQL Flexible Server**（实例名：`aimeelan-server`，数据库：`aimeelan-database`）
作为持久化存储层，管理访客、博客、项目、分析等全部业务数据。

---

## 目录

- [架构概览](#架构概览)
- [连接配置](#连接配置)
  - [环境变量](#环境变量)
  - [连接字符串解析](#连接字符串解析)
  - [连接方式](#连接方式)
- [数据库 Schema](#数据库-schema)
  - [ER 关系图](#er-关系图)
  - [表结构详解](#表结构详解)
  - [索引设计](#索引设计)
- [各模块 SQL 操作详解](#各模块-sql-操作详解)
  - [访客注册](#1-访客注册-visitor-verification)
  - [页面浏览追踪](#2-页面浏览追踪-page-view-tracking)
  - [点击追踪](#3-点击追踪-click-tracking)
  - [留言系统](#4-留言系统-contact-messages)
  - [博客文章](#5-博客文章-blog-posts)
  - [标签系统](#6-标签系统-tags)
  - [GitHub 项目](#7-github-项目-projects)
  - [Admin 统计面板](#8-admin-统计面板-analytics)
  - [访客分页查询](#9-访客分页查询)
  - [CSV 数据导出](#10-csv-数据导出)
  - [留存分析](#11-留存分析-retention)
- [数据初始化（Seed）](#数据初始化seed)
- [连接管理模式](#连接管理模式)
- [Azure 门户监控](#azure-门户监控)
  - [关键指标说明](#关键指标说明)
  - [如何设置 Metrics 图表](#如何设置-metrics-图表)
  - [告警配置建议](#告警配置建议)
- [常用维护命令](#常用维护命令)
  - [连接到数据库](#连接到数据库)
  - [数据查询](#数据查询)
  - [性能诊断](#性能诊断)
  - [数据清理](#数据清理)
- [性能优化说明](#性能优化说明)
- [FAQ](#faq)

---

## 架构概览

```
Flask API
  │
  ├── get_db()  ──→  psycopg2.connect(DATABASE_URL, sslmode="require")
  │                       │
  │                       └──→ Azure PostgreSQL Flexible Server
  │                            ├── aimeelan-database
  │                            │     ├── visitors        （访客表）
  │                            │     ├── click_logs      （点击日志）
  │                            │     ├── messages        （留言表）
  │                            │     ├── page_views      （PV 表）
  │                            │     ├── visitor_sessions （会话表）
  │                            │     ├── posts           （博客文章）
  │                            │     ├── tags            （标签表）
  │                            │     ├── post_tags       （文章-标签关联）
  │                            │     └── projects        （GitHub 项目）
  │                            └── SSL 加密连接（端口 5432）
  │
  └── init_db()  ──→  CREATE TABLE IF NOT EXISTS（启动时自动建表）
```

---

## 连接配置

### 环境变量

Azure App Service 自动注入 PostgreSQL 连接字符串，代码按优先级读取：

| 环境变量名 | 优先级 | 说明 |
|---|---|---|
| `AZURE_POSTGRESQL_CONNECTIONSTRING` | 1（最高） | 在 App Service 环境变量中手动配置 |
| `CUSTOMCONNSTR_AZURE_POSTGRESQL_CONNECTIONSTRING` | 2 | Azure Service Connector 自动绑定时的前缀格式 |
| 本地默认值 | 3 | `host=localhost dbname=portfoliodb user=postgres password=postgres` |

### 连接字符串解析

Azure 提供的格式是 **ADO.NET 风格**（分号分隔）：
```
Server=aimeelan-server.postgres.database.azure.com;Database=aimeelan-database;Port=5432;User Id=xxxxx;Password=xxxxx;
```

`_parse_pg_conn()` 函数将其转换为 **psycopg2（libpq）格式**（空格分隔）：
```
host=aimeelan-server.postgres.database.azure.com dbname=aimeelan-database user=xxxxx password=xxxxx
```

```python
def _parse_pg_conn(raw):
    if not raw or raw.startswith("host="):    # 已经是 libpq 格式，直接返回
        return raw
    parts = dict(p.split("=", 1) for p in raw.split(";") if "=" in p)
    return (
        f"host={parts.get('Server','')} "
        f"dbname={parts.get('Database','')} "
        f"user={parts.get('User Id','')} "
        f"password={parts.get('Password','')}"
    )
```

### 连接方式

```python
def get_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    return conn
```

- **psycopg2**：Python 最成熟的 PostgreSQL 驱动
- **sslmode="require"**：强制 SSL 加密，Azure PostgreSQL 要求必须启用
- 每次请求获取新连接，用完即关闭（无连接池）

---

## 数据库 Schema

### ER 关系图

```
visitors (1) ───< (N) click_logs
    │
    ├───────────< (N) messages
    │
    ├───────────< (N) page_views
    │
    └───────────< (N) visitor_sessions

posts (1) ───< (N) post_tags >── (1) tags

projects （独立表，无外键关联）
```

### 表结构详解

#### 1. `visitors` — 访客表

| 列名 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | 自增主键 |
| `name` | TEXT | NOT NULL | 访客姓名 |
| `email` | TEXT | NOT NULL | 访客邮箱 |
| `verified` | INTEGER | DEFAULT 0 | 验证状态（1=已验证） |
| `token` | TEXT | | 验证令牌 |
| `created_at` | TIMESTAMP | DEFAULT NOW() | 注册时间 |

**用途**：入口验证页面（verify.html）中收集的访客信息。

#### 2. `click_logs` — 点击日志表

| 列名 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | 自增主键 |
| `visitor_id` | INTEGER | REFERENCES visitors(id) | 关联访客 |
| `element` | TEXT | NOT NULL | 被点击的按钮/链接标识（如 `nav-blog`） |
| `page` | TEXT | | 点击发生的页面 |
| `clicked_at` | TIMESTAMP | DEFAULT NOW() | 点击时间 |

**用途**：前端 `data-track` 属性标记的所有可点击元素。

#### 3. `messages` — 留言表

| 列名 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | 自增主键 |
| `visitor_id` | INTEGER | REFERENCES visitors(id) | 关联访客 |
| `name` | TEXT | NOT NULL | 发送者姓名 |
| `email` | TEXT | NOT NULL | 发送者邮箱 |
| `message` | TEXT | NOT NULL | 留言内容 |
| `sent_at` | TIMESTAMP | DEFAULT NOW() | 发送时间 |

**用途**：Contact 表单提交的消息，同时触发 SMTP 邮件通知。

#### 4. `page_views` — 页面浏览表

| 列名 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | 自增主键 |
| `visitor_id` | INTEGER | REFERENCES visitors(id) | 关联访客（可为 NULL） |
| `page` | TEXT | NOT NULL | 页面路径（如 `/`, `/blog`） |
| `referrer` | TEXT | | 来源页面 URL |
| `user_agent` | TEXT | | 浏览器 UA 字符串（截取前 500 字符） |
| `ip_hash` | TEXT | | IP 地址的 SHA-256 哈希（隐私保护） |
| `duration_sec` | INTEGER | DEFAULT 0 | 页面停留时间（秒） |
| `screen_width` | INTEGER | | 屏幕宽度（用于设备类型分析） |
| `created_at` | TIMESTAMP | DEFAULT NOW() | 浏览时间 |

**用途**：最核心的分析数据源——支撑 Admin 面板的 PV 趋势、设备分布、TOP 页面、留存分析。

#### 5. `visitor_sessions` — 访客会话表

| 列名 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | 自增主键 |
| `visitor_id` | INTEGER | REFERENCES visitors(id) | 关联访客 |
| `session_token` | TEXT | UNIQUE | 会话令牌（用于关联同一次访问的多个 PV） |
| `started_at` | TIMESTAMP | DEFAULT NOW() | 会话开始时间 |
| `ended_at` | TIMESTAMP | | 会话结束时间 |
| `page_count` | INTEGER | DEFAULT 0 | 本次会话的页面浏览数 |

**用途**：追踪单次访问的深度（浏览了多少个页面、停留多久）。

#### 6. `posts` — 博客文章表

| 列名 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | 自增主键 |
| `slug` | TEXT | UNIQUE NOT NULL | URL 友好标识（如 `azure-openai-service-troubleshooting-guide`） |
| `title` | TEXT | NOT NULL | 文章标题 |
| `summary` | TEXT | | 摘要 |
| `content` | TEXT | NOT NULL | Markdown 正文 |
| `status` | TEXT | DEFAULT 'published' | 状态：`published` / `draft` |
| `views` | INTEGER | DEFAULT 0 | 浏览次数 |
| `published_at` | TIMESTAMP | DEFAULT NOW() | 发布时间 |
| `updated_at` | TIMESTAMP | DEFAULT NOW() | 更新时间 |
| `created_at` | TIMESTAMP | DEFAULT NOW() | 创建时间 |

**用途**：博客 CMS 的核心表。`slug` 用于 URL 路由（`/blog/azure-openai-...`）。

#### 7. `tags` — 标签表

| 列名 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | 自增主键 |
| `name` | TEXT | UNIQUE NOT NULL | 标签名（如 `Azure`、`Python`） |

#### 8. `post_tags` — 文章-标签关联表

| 列名 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `post_id` | INTEGER | REFERENCES posts(id) ON DELETE CASCADE | 文章 ID |
| `tag_id` | INTEGER | REFERENCES tags(id) ON DELETE CASCADE | 标签 ID |
|  | | PRIMARY KEY (post_id, tag_id) | 联合主键 |

**关系**：多对多（一篇文章可有多个标签，一个标签可属于多篇文章）。`ON DELETE CASCADE` 确保删除文章/标签时自动清理关联。

#### 9. `projects` — GitHub 项目表

| 列名 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | 自增主键 |
| `github_repo` | TEXT | UNIQUE | 仓库全名（如 `hahAI111/aimeewebpage`） |
| `name` | TEXT | NOT NULL | 仓库名 |
| `description` | TEXT | | 仓库描述 |
| `language` | TEXT | | 主要编程语言 |
| `stars` | INTEGER | DEFAULT 0 | Star 数 |
| `forks` | INTEGER | DEFAULT 0 | Fork 数 |
| `open_issues` | INTEGER | DEFAULT 0 | 开放 Issue 数 |
| `homepage` | TEXT | | 项目主页 URL |
| `last_commit_at` | TIMESTAMP | | 最后提交时间 |
| `featured` | BOOLEAN | DEFAULT FALSE | 是否精选展示 |
| `synced_at` | TIMESTAMP | DEFAULT NOW() | 最后同步时间 |

**用途**：通过 GitHub API 同步的仓库数据。`ON CONFLICT (github_repo) DO UPDATE` 实现 upsert。

### 索引设计

```sql
CREATE INDEX idx_pv_visitor       ON page_views(visitor_id);  -- 按访客查 PV
CREATE INDEX idx_pv_created       ON page_views(created_at);  -- 按时间范围查 PV（趋势图）
CREATE INDEX idx_click_time       ON click_logs(clicked_at);  -- 按时间查点击（趋势分析）
CREATE INDEX idx_visitors_created ON visitors(created_at);    -- 按时间查访客（趋势图）
CREATE INDEX idx_posts_slug       ON posts(slug);             -- 按 slug 查文章（URL 路由）
CREATE INDEX idx_posts_status     ON posts(status);           -- 按状态筛选（published/draft）
```

**设计原则**：
- `page_views` 是数据量最大的表，`visitor_id` 和 `created_at` 索引覆盖了分析查询和留存查询
- `posts.slug` 索引保证文章详情页 O(1) 查找
- 所有索引都用 `CREATE INDEX IF NOT EXISTS`，重启安全

---

## 各模块 SQL 操作详解

### 1. 访客注册 (Visitor Verification)

**触发**：`POST /api/verify`

```sql
INSERT INTO visitors (name, email, verified, token)
VALUES (%s, %s, 1, %s)
RETURNING id;
```

- `RETURNING id`：PostgreSQL 特性，插入后立即返回自增 ID（避免额外一次查询）
- `verified = 1`：直接标记为已验证
- `token`：随机令牌（`secrets.token_urlsafe(32)`），当前未用于邮件验证，预留字段

**写入频率**：每个新访客 1 次

### 2. 页面浏览追踪 (Page View Tracking)

**触发**：`POST /api/pageview`（前端 `script.js` 在页面加载和 `beforeunload` 时自动发送）

```sql
-- 记录 PV
INSERT INTO page_views (visitor_id, page, referrer, user_agent, ip_hash, duration_sec, screen_width)
VALUES (%s, %s, %s, %s, %s, %s, %s);

-- 更新已有会话
UPDATE visitor_sessions
SET page_count = page_count + 1, ended_at = NOW()
WHERE session_token = %s;

-- 或创建新会话
INSERT INTO visitor_sessions (visitor_id, session_token, page_count)
VALUES (%s, %s, 1);
```

**隐私保护**：
- `ip_hash`：IP 地址经过 SHA-256 哈希，不存储原始 IP
- `user_agent`：截取前 500 字符，防止超长字符串

**写入频率**：每次页面浏览 1-2 条写入（最高频的写操作）

### 3. 点击追踪 (Click Tracking)

**触发**：`POST /api/track`

```sql
INSERT INTO click_logs (visitor_id, element, page)
VALUES (%s, %s, %s);
```

**写入频率**：每次前端点击带 `data-track` 属性的元素

### 4. 留言系统 (Contact Messages)

**触发**：`POST /api/contact`

```sql
INSERT INTO messages (visitor_id, name, email, message)
VALUES (%s, %s, %s, %s);
```

**写入频率**：低（访客手动提交）

### 5. 博客文章 (Blog Posts)

**文章列表**：`GET /api/posts?tag=Azure&page=1&per_page=10`

```sql
-- 带标签筛选
SELECT p.id, p.slug, p.title, p.summary, p.views, p.published_at::text as published_at
FROM posts p
JOIN post_tags pt ON p.id = pt.post_id
JOIN tags t ON pt.tag_id = t.id
WHERE p.status = 'published' AND t.name = %s
ORDER BY p.published_at DESC
LIMIT %s OFFSET %s;

-- 无标签筛选
SELECT id, slug, title, summary, views, published_at::text as published_at
FROM posts WHERE status = 'published'
ORDER BY published_at DESC
LIMIT %s OFFSET %s;

-- 为每篇文章加载标签
SELECT t.name FROM tags t
JOIN post_tags pt ON t.id = pt.tag_id
WHERE pt.post_id = %s;

-- 总数（分页用）
SELECT COUNT(*) as c FROM posts WHERE status = 'published';
```

**文章详情**：`GET /api/posts/<slug>`

```sql
SELECT id, slug, title, summary, content, views, status,
       published_at::text as published_at, updated_at::text as updated_at
FROM posts WHERE slug = %s;

-- 加载标签
SELECT t.name FROM tags t
JOIN post_tags pt ON t.id = pt.tag_id
WHERE pt.post_id = %s;

-- 更新浏览量
UPDATE posts SET views = views + 1 WHERE slug = %s;
```

**说明**：
- `::text` 将 TIMESTAMP 转为字符串，便于 JSON 序列化
- `LIMIT %s OFFSET %s`：服务端分页
- 浏览量每次访问 +1（即使缓存命中也会执行 UPDATE）

### 6. 标签系统 (Tags)

**标签列表**：`GET /api/tags`

```sql
SELECT t.name, COUNT(pt.post_id) as post_count
FROM tags t
LEFT JOIN post_tags pt ON t.id = pt.tag_id
LEFT JOIN posts p ON pt.post_id = p.id AND p.status = 'published'
GROUP BY t.name
HAVING COUNT(pt.post_id) > 0
ORDER BY post_count DESC;
```

**说明**：`HAVING COUNT > 0` 过滤掉没有已发布文章的空标签。

### 7. GitHub 项目 (Projects)

**读取**：`GET /api/projects`

```sql
SELECT id, github_repo, name, description, language, stars, forks,
       open_issues, homepage, featured,
       last_commit_at::text as last_commit_at, synced_at::text as synced_at
FROM projects
ORDER BY featured DESC, stars DESC, last_commit_at DESC NULLS LAST;
```

**同步（Upsert）**：`POST /api/projects/sync`

```sql
INSERT INTO projects (github_repo, name, description, language, stars, forks,
                      open_issues, homepage, last_commit_at, synced_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
ON CONFLICT (github_repo) DO UPDATE SET
    name=EXCLUDED.name, description=EXCLUDED.description, language=EXCLUDED.language,
    stars=EXCLUDED.stars, forks=EXCLUDED.forks, open_issues=EXCLUDED.open_issues,
    homepage=EXCLUDED.homepage, last_commit_at=EXCLUDED.last_commit_at, synced_at=NOW();
```

**说明**：
- `ON CONFLICT ... DO UPDATE`：PostgreSQL 的 **Upsert** 语法——如果 `github_repo` 已存在则更新，否则插入
- `EXCLUDED`：引用 INSERT 中被拒绝的新值
- `NULLS LAST`：没有最后提交时间的排在最后
- 排序优先级：精选 > Star 数 > 最后提交时间

### 8. Admin 统计面板 (Analytics)

**触发**：`GET /api/admin/stats`（需 Admin 登录）

共 8 条查询，一次性返回完整统计数据：

```sql
-- 1. 总计数（KPI 卡片）
SELECT COUNT(*) as c FROM visitors;
SELECT COUNT(*) as c FROM click_logs;
SELECT COUNT(*) as c FROM messages;
SELECT COUNT(*) as c FROM page_views;
SELECT COUNT(*) as c FROM posts WHERE status = 'published';

-- 2. 最近 30 天访客趋势（折线图）
SELECT DATE(created_at)::text as day, COUNT(*) as count
FROM visitors
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY DATE(created_at) ORDER BY day;

-- 3. 最近 30 天 PV 趋势（折线图）
SELECT DATE(created_at)::text as day, COUNT(*) as count
FROM page_views
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY DATE(created_at) ORDER BY day;

-- 4. 热门点击元素 Top 15（柱状图）
SELECT element, COUNT(*) as clicks
FROM click_logs GROUP BY element
ORDER BY clicks DESC LIMIT 15;

-- 5. 热门页面 Top 10 + 平均停留时间
SELECT page, COUNT(*) as views,
       COALESCE(AVG(duration_sec)::int, 0) as avg_duration
FROM page_views GROUP BY page
ORDER BY views DESC LIMIT 10;

-- 6. 邮箱域名分布 Top 15（了解访客来源公司）
SELECT SPLIT_PART(email, '@', 2) as domain, COUNT(*) as count
FROM visitors GROUP BY domain
ORDER BY count DESC LIMIT 15;

-- 7. 设备类型分布（饼图）
SELECT CASE
    WHEN screen_width IS NULL THEN 'Unknown'
    WHEN screen_width < 768  THEN 'Mobile'
    WHEN screen_width < 1024 THEN 'Tablet'
    ELSE 'Desktop'
END as device, COUNT(*) as count
FROM page_views GROUP BY device
ORDER BY count DESC;

-- 8. 最新留言 + 热门文章
SELECT id, name, email, message, sent_at::text FROM messages ORDER BY sent_at DESC LIMIT 10;
SELECT slug, title, views, published_at::text FROM posts WHERE status='published' ORDER BY views DESC LIMIT 10;
```

**SQL 技巧**：
- `DATE(created_at)`：提取日期部分，用于 GROUP BY 天
- `NOW() - INTERVAL '30 days'`：PostgreSQL 的时间运算
- `SPLIT_PART(email, '@', 2)`：提取邮箱域名
- `COALESCE(..., 0)`：NULL 安全的默认值
- `CASE WHEN`：将连续数据（screen_width）分类为离散标签

### 9. 访客分页查询

**触发**：`GET /api/admin/visitors?page=1&per_page=20&domain=microsoft.com`

```sql
-- 带域名筛选
SELECT id, name, email, created_at::text as created_at
FROM visitors WHERE email LIKE %s
ORDER BY created_at DESC LIMIT %s OFFSET %s;

SELECT COUNT(*) as c FROM visitors WHERE email LIKE %s;

-- 无筛选
SELECT id, name, email, created_at::text as created_at
FROM visitors ORDER BY created_at DESC LIMIT %s OFFSET %s;

SELECT COUNT(*) as c FROM visitors;
```

**说明**：域名筛选用 `LIKE '%@microsoft.com'` 模式匹配。

### 10. CSV 数据导出

**触发**：`GET /api/admin/export/<table>`

```sql
SELECT * FROM {table} ORDER BY id DESC LIMIT 5000;
```

**安全设计**：`table` 参数必须在白名单 `{"visitors", "click_logs", "messages", "page_views"}` 中，
防止 SQL 注入。限制 5000 行避免内存溢出。

### 11. 留存分析 (Retention)

**触发**：`GET /api/admin/retention`

```sql
WITH first_visit AS (
    -- 每个访客的首次访问日期
    SELECT visitor_id, DATE(MIN(created_at)) as first_day
    FROM page_views WHERE visitor_id IS NOT NULL
    GROUP BY visitor_id
),
daily_activity AS (
    -- 每个访客每天是否活跃（去重）
    SELECT DISTINCT visitor_id, DATE(created_at) as active_day
    FROM page_views WHERE visitor_id IS NOT NULL
)
SELECT
    fv.first_day::text as cohort_date,
    COUNT(DISTINCT fv.visitor_id) as cohort_size,
    -- Day 0: 首日（= cohort_size）
    COUNT(DISTINCT CASE WHEN da.active_day = fv.first_day     THEN da.visitor_id END) as day_0,
    -- Day 1: 次日回访
    COUNT(DISTINCT CASE WHEN da.active_day = fv.first_day + 1 THEN da.visitor_id END) as day_1,
    -- Day 7: 一周后回访
    COUNT(DISTINCT CASE WHEN da.active_day = fv.first_day + 7 THEN da.visitor_id END) as day_7,
    -- Day 30: 一个月后回访
    COUNT(DISTINCT CASE WHEN da.active_day = fv.first_day + 30 THEN da.visitor_id END) as day_30
FROM first_visit fv
LEFT JOIN daily_activity da ON fv.visitor_id = da.visitor_id
WHERE fv.first_day > NOW() - INTERVAL '60 days'
GROUP BY fv.first_day
ORDER BY fv.first_day DESC LIMIT 30;
```

**SQL 技巧**：
- **CTE（WITH 子句）**：将复杂逻辑拆分为可读的命名子查询
- **留存定义**：Day N = 首次访问后第 N 天是否有活跃记录
- **`fv.first_day + 1`**：PostgreSQL 的日期加法，直接加整数天
- **`COUNT(DISTINCT CASE WHEN ...)`**：条件计数，只计算满足条件的唯一访客
- 这是整个应用中最复杂的 SQL，也是最适合被 Redis 缓存的查询（TTL 300s）

---

## 数据初始化（Seed）

应用启动时 `init_db()` 自动执行：

```
init_db()
  │
  ├── CREATE TABLE IF NOT EXISTS × 9 张表
  ├── CREATE INDEX IF NOT EXISTS × 6 个索引
  ├── COMMIT
  │
  ├── 检查 posts 表是否为空？
  │     └── 是 → _seed_blog_posts()：插入 5 篇示例文章 + 10 个标签
  │
  └── 检查 projects 表是否为空？
        └── 是 → _seed_github_projects()：调用 GitHub API 同步仓库
```

### 博客 Seed 数据

自动创建 5 篇文章：

| Slug | 标签 |
|---|---|
| `azure-openai-service-troubleshooting-guide` | Azure, AI, Troubleshooting |
| `building-ai-support-diagnostic-tools-python` | Python, AI, Azure, DevOps |
| `postgresql-query-optimization-real-cases` | SQL, Azure, Troubleshooting |
| `azure-networking-private-endpoints-explained` | Azure, Networking, Cloud |
| `my-journey-from-ai-support-to-building-tools` | Career, AI, Azure |

### 标签 Seed 数据

10 个预设标签：Azure, AI, Python, Troubleshooting, DevOps, Machine Learning, Cloud, SQL, Networking, Career

### Seed SQL 模式

```sql
-- 文章插入（跳过已存在的）
INSERT INTO posts (slug, title, summary, content, status, published_at)
VALUES (%s, %s, %s, %s, 'published', NOW())
ON CONFLICT (slug) DO NOTHING RETURNING id;

-- 标签插入（跳过已存在的）
INSERT INTO tags (name) VALUES (%s)
ON CONFLICT (name) DO NOTHING;

-- 关联插入（跳过已存在的）
INSERT INTO post_tags (post_id, tag_id) VALUES (%s, %s)
ON CONFLICT DO NOTHING;
```

`ON CONFLICT DO NOTHING` 保证重复启动不会产生重复数据。

---

## 连接管理模式

当前采用 **短连接模式**（每次请求新建连接，用完关闭）：

```python
conn = get_db()
cur = conn.cursor()
cur.execute(...)
conn.commit()
cur.close()
conn.close()
```

**优点**：简单、可靠、无连接泄漏风险  
**缺点**：每次请求都有 TCP + SSL 握手开销（~10-20ms）

**未来优化**：如果流量增长，可引入连接池：
```python
# 方案：psycopg2.pool.ThreadedConnectionPool
from psycopg2.pool import ThreadedConnectionPool
pool = ThreadedConnectionPool(2, 10, DATABASE_URL, sslmode="require")
conn = pool.getconn()
# ... 使用 ...
pool.putconn(conn)
```

---

## Azure 门户监控

### 关键指标说明

打开 Azure Portal → `aimeelan-server` → **监视 → 指标 (Metrics)**

| 指标名称 | 含义 | 正常范围 |
|---|---|---|
| **CPU percent** | 数据库服务器 CPU 使用率 | < 70% |
| **Memory percent** | 内存使用率 | < 80% |
| **Active Connections** | 当前活跃连接数 | 1-10（gunicorn workers） |
| **Storage percent** | 磁盘空间使用率 | < 80% |
| **Storage Used** | 已用存储（MB） | 当前数据量小，< 100MB |
| **Maximum Used Transaction IDs** | 事务 ID 使用量 | < 50%（接近上限需 VACUUM） |
| **Read IOPS / Write IOPS** | 磁盘每秒读/写操作数 | 写 IOPS 集中在 PV 记录时 |
| **Network Bytes In/Out** | 网络流量 | 取决于查询结果大小 |
| **Succeeded Connections** | 成功建立的连接数 | 应等于请求数（短连接模式） |
| **Failed Connections** | 连接失败数 | 应保持 0 |
| **Deadlocks** | 死锁次数 | 应保持 0 |
| **Database Size** | 数据库大小 | 缓慢增长正常 |

### 如何设置 Metrics 图表

Azure Portal → `aimeelan-server` → **监视 → 指标**

**图表 1：服务器健康**
- CPU percent + Memory percent
- 时间范围：过去 24 小时
- 用途：确保服务器未过载

**图表 2：连接状况**
- Active Connections + Failed Connections
- 时间范围：过去 6 小时
- 用途：监控连接是否正常

**图表 3：存储增长**
- Storage Used
- 时间范围：过去 30 天
- 用途：预估存储扩容需求

**图表 4：IO 活动**
- Read IOPS + Write IOPS
- 时间范围：过去 1 小时
- 用途：识别高负载时段

### 告警配置建议

Azure Portal → `aimeelan-server` → **监视 → 警报 → + 创建警报规则**

| 告警 | 条件 | 严重程度 |
|---|---|---|
| CPU 过高 | CPU percent > 80% 持续 5 分钟 | 严重 |
| 连接失败 | Failed Connections > 5 / 5 分钟 | 严重 |
| 存储空间 | Storage percent > 80% | 警告 |
| 死锁 | Deadlocks > 0 | 警告 |
| 连接数过多 | Active Connections > 50 | 警告 |

---

## 常用维护命令

### 连接到数据库

**方式 1：Azure Portal → `aimeelan-server` → 连接**

使用 Cloud Shell 或 Azure Data Studio 直接连接。

**方式 2：本地 psql（需要配置防火墙规则允许你的 IP）**

```bash
psql "host=aimeelan-server.postgres.database.azure.com dbname=aimeelan-database user=<your-user> sslmode=require"
```

**方式 3：Azure Portal → `aimeelan-database` → 查询编辑器（预览）**

### 数据查询

```sql
-- 查看所有表
\dt

-- 各表数据量
SELECT schemaname, relname, n_live_tup
FROM pg_stat_user_tables ORDER BY n_live_tup DESC;

-- 最近 10 个访客
SELECT * FROM visitors ORDER BY created_at DESC LIMIT 10;

-- 最近 10 条 PV
SELECT * FROM page_views ORDER BY created_at DESC LIMIT 10;

-- 某天的访客总数和 PV 数
SELECT
    (SELECT COUNT(*) FROM visitors WHERE DATE(created_at) = '2026-03-11') as visitors,
    (SELECT COUNT(*) FROM page_views WHERE DATE(created_at) = '2026-03-11') as pageviews;

-- 各页面访问排行
SELECT page, COUNT(*) as views, AVG(duration_sec)::int as avg_sec
FROM page_views GROUP BY page ORDER BY views DESC;

-- 文章浏览排行
SELECT slug, title, views FROM posts ORDER BY views DESC;

-- 各邮箱域名分布
SELECT SPLIT_PART(email, '@', 2) as domain, COUNT(*)
FROM visitors GROUP BY domain ORDER BY count DESC LIMIT 10;
```

### 性能诊断

```sql
-- 查看表大小
SELECT relname,
       pg_size_pretty(pg_total_relation_size(relid)) as total_size,
       pg_size_pretty(pg_relation_size(relid)) as table_size,
       pg_size_pretty(pg_indexes_size(relid)) as index_size
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC;

-- 查看索引使用情况
SELECT indexrelname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes ORDER BY idx_scan DESC;

-- 查看死元组（需要 VACUUM 的表）
SELECT relname, n_live_tup, n_dead_tup,
       ROUND(100.0 * n_dead_tup / GREATEST(n_live_tup + n_dead_tup, 1), 1) as dead_pct,
       last_vacuum, last_autovacuum
FROM pg_stat_user_tables WHERE n_dead_tup > 100 ORDER BY dead_pct DESC;

-- 查看最慢的查询（需启用 pg_stat_statements 扩展）
SELECT query, calls, mean_exec_time::numeric(10,2) as avg_ms,
       total_exec_time::numeric(10,2) as total_ms
FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;

-- 查看当前活跃连接
SELECT pid, usename, application_name, client_addr, state, query
FROM pg_stat_activity WHERE datname = 'aimeelan-database';
```

### 数据清理

```sql
-- 删除 90 天前的 PV 记录（释放空间）
DELETE FROM page_views WHERE created_at < NOW() - INTERVAL '90 days';

-- 删除 90 天前的点击日志
DELETE FROM click_logs WHERE clicked_at < NOW() - INTERVAL '90 days';

-- 清理后执行 VACUUM
VACUUM ANALYZE page_views;
VACUUM ANALYZE click_logs;

-- 手动回收空间（大量删除后）
VACUUM FULL page_views;  -- 注意：会锁表
```

---

## 性能优化说明

### 当前已实现的优化

| 优化 | 作用 |
|---|---|
| 6 个 B-tree 索引 | 加速 WHERE/JOIN/ORDER BY |
| Redis 缓存层 | 减少重复查询（详见 REDIS.md） |
| `LIMIT + OFFSET` 分页 | 避免全表扫描 |
| `ON CONFLICT DO NOTHING/UPDATE` | 原子 Upsert，无需 SELECT 再判断 |
| `RETURNING id` | 插入后直接获取 ID，省一次 SELECT |
| `::text` 类型转换 | 在数据库层转换，减少 Python 侧处理 |

### 可进一步优化（流量增长后）

| 方向 | 方案 |
|---|---|
| 连接池 | 引入 `psycopg2.pool.ThreadedConnectionPool` |
| 游标分页 | 大表用 keyset pagination 替代 OFFSET |
| 分区表 | `page_views` 按月分区，加速时间范围查询 |
| 只读副本 | Admin 面板查询走 Read Replica |
| 批量写入 | PV 先用 Redis 队列缓冲，批量 INSERT |
| `pg_stat_statements` | 启用后可分析慢查询 |

---

## FAQ

**Q：数据库会自动建表吗？**  
A：是。`init_db()` 在应用启动时自动执行 `CREATE TABLE IF NOT EXISTS`，无需手动建表。

**Q：重复启动会产生重复数据吗？**  
A：不会。所有建表语句用 `IF NOT EXISTS`，Seed 数据用 `ON CONFLICT DO NOTHING`。

**Q：page_views 表会不会无限增长？**  
A：会。建议定期清理 90 天前的数据（见"数据清理"章节），或在 Admin 面板中导出 CSV 存档后删除。

**Q：为什么用短连接而不用连接池？**  
A：当前流量低，短连接足够且代码简单。连接池在并发 > 50 时才有明显优势。

**Q：如何备份数据库？**  
A：Azure PostgreSQL Flexible Server 自动每日备份，保留 7-35 天（可在 Azure Portal 配置）。
手动备份：Azure Portal → `aimeelan-server` → 备份和还原。

**Q：能从本地连接到 Azure 数据库吗？**  
A：可以。需在 Azure Portal → `aimeelan-server` → 网络 中将你的 IP 加入防火墙白名单。

**Q：密码存在哪里？**  
A：连接字符串存在 Azure App Service 的环境变量中，不在代码里。本地开发使用默认的 localhost 配置。
