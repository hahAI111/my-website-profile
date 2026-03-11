# Redis Cache — 使用说明与监控指南

本项目使用 **Azure Cache for Redis**（实例名：`aimee-cache`，Basic SKU）作为缓存层，
减少 PostgreSQL 的查询压力，加速 API 响应。

---

## 目录

- [架构概览](#架构概览)
- [连接配置](#连接配置)
- [核心函数](#核心函数)
- [缓存键（Cache Keys）一览](#缓存键cache-keys一览)
- [各 API 缓存流程详解](#各-api-缓存流程详解)
  - [博客文章列表](#1-博客文章列表)
  - [单篇文章详情](#2-单篇文章详情)
  - [标签列表](#3-标签列表)
  - [GitHub 项目列表](#4-github-项目列表)
  - [Admin 统计面板](#5-admin-统计面板)
  - [留存分析](#6-留存分析)
- [缓存失效策略](#缓存失效策略)
- [容错设计](#容错设计)
- [Azure 门户监控](#azure-门户监控)
  - [关键指标说明](#关键指标说明)
  - [如何设置 Metrics 图表](#如何设置-metrics-图表)
  - [告警配置建议](#告警配置建议)
- [控制台命令测试](#控制台命令测试)
  - [常用命令](#常用命令)
  - [完整测试流程](#完整测试流程)
- [性能对比](#性能对比)
- [FAQ](#faq)

---

## 架构概览

```
用户请求 → Flask API
              │
              ├── cache_get(key) ──→ Redis（命中？）
              │        ├── 命中 ──→ 直接返回 JSON（~1ms）
              │        └── 未命中 ──┐
              │                     ▼
              ├── 查询 PostgreSQL（~50-100ms）
              │
              └── cache_set(key, result, ttl) ──→ 写入 Redis
                                                  （TTL 秒后自动过期）
```

Redis 在本项目中扮演 **Read-Through Cache** 的角色：
1. 先查 Redis，命中则跳过数据库
2. 未命中则查 PostgreSQL，将结果写入 Redis
3. 数据更新时主动清除相关缓存

---

## 连接配置

### 环境变量

Azure App Service 自动注入 Redis 连接字符串，代码按优先级读取：

```
AZURE_REDIS_CONNECTIONSTRING    ← 优先
REDISCACHECONNSTR_azure_redis_cache   ← 备用（Azure 自动绑定时的前缀格式）
```

### 连接字符串解析

Azure 提供的格式是 ADO.NET 风格：
```
aimee-cache.redis.cache.windows.net:6380,password=xxxxx,ssl=True,abortConnect=False
```

`_parse_redis_conn()` 函数将其转换为 Python `redis` 库所需的 URI 格式：
```
rediss://:xxxxx@aimee-cache.redis.cache.windows.net:6380/0
```

- `rediss://` = TLS/SSL 连接（注意多了一个 `s`）
- 端口 `6380` = Azure Redis 的 SSL 端口
- `/0` = 使用 Redis database 0

### 连接初始化

```python
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
redis_client.ping()  # 验证连接
```

`decode_responses=True` 表示自动将字节解码为字符串，省去手动 `.decode()`。

---

## 核心函数

代码中定义了 3 个缓存工具函数，位于 `app.py`：

### `cache_get(key)`

```python
def cache_get(key):
    if redis_client:
        val = redis_client.get(key)           # Redis GET 命令
        return json.loads(val) if val else None  # JSON 反序列化
    return None
```

- 底层命令：`GET <key>`
- 返回值：Python dict/list（命中）或 `None`（未命中/Redis 不可用）
- 时间复杂度：O(1)

### `cache_set(key, value, ttl=300)`

```python
def cache_set(key, value, ttl=300):
    if redis_client:
        redis_client.setex(key, ttl, json.dumps(value))  # SET + EXPIRE 原子操作
```

- 底层命令：`SETEX <key> <ttl> <json_string>`
- `ttl`：过期时间（秒），到期后 Redis 自动删除该 key
- 数据格式：JSON 字符串序列化存储
- 时间复杂度：O(1)

### `cache_delete(pattern)`

```python
def cache_delete(pattern):
    if redis_client:
        for key in redis_client.scan_iter(match=pattern):
            redis_client.delete(key)
```

- 底层命令：`SCAN 0 MATCH <pattern>` + `DEL <key>`
- 用途：按通配符模式批量删除缓存（如 `stats:*` 删除所有统计缓存）
- `SCAN` 使用游标遍历，不会像 `KEYS *` 阻塞 Redis
- 时间复杂度：O(N)，N = 匹配的 key 数量

---

## 缓存键（Cache Keys）一览

| Key 格式 | 示例 | TTL | 来源 API |
|---|---|---|---|
| `posts:list:{tag}:{page}:{per_page}` | `posts:list::1:10` | 120s | `GET /api/posts` |
| `post:{slug}` | `post:azure-openai-service-troubleshooting-guide` | 300s | `GET /api/posts/<slug>` |
| `tags:all` | `tags:all` | 300s | `GET /api/tags` |
| `projects:all` | `projects:all` | 300s | `GET /api/projects` |
| `stats:overview` | `stats:overview` | 60s | `GET /api/admin/stats` |
| `stats:retention` | `stats:retention` | 300s | `GET /api/admin/retention` |

**TTL 设计原则**：
- 60 秒：实时性要求高的数据（Admin 统计面板）
- 120 秒：频繁变化的列表数据（文章列表带分页）
- 300 秒：相对稳定的数据（单篇文章、标签、项目、留存分析）

---

## 各 API 缓存流程详解

### 1. 博客文章列表

**路由**：`GET /api/posts?tag=Azure&page=1&per_page=10`  
**缓存键**：`posts:list:Azure:1:10`  
**TTL**：120 秒

```
请求 → cache_get("posts:list:Azure:1:10")
         │
         ├── 命中 → 直接返回 JSON
         │
         └── 未命中
              ├── PostgreSQL: SELECT posts + JOIN tags（分页查询）
              ├── PostgreSQL: SELECT COUNT(*)（总数）
              ├── 组装 {posts, total, page, per_page}
              ├── cache_set(key, result, ttl=120) → 存入 Redis
              └── 返回 JSON
```

**说明**：不同的 tag/page/per_page 组合会生成不同的缓存键，互不影响。

### 2. 单篇文章详情

**路由**：`GET /api/posts/azure-openai-service-troubleshooting-guide`  
**缓存键**：`post:azure-openai-service-troubleshooting-guide`  
**TTL**：300 秒

```
请求 → cache_get("post:azure-openai-...")
         │
         ├── 命中
         │     ├── UPDATE posts SET views = views + 1  ← 仍然更新浏览量
         │     └── 返回缓存的 JSON
         │
         └── 未命中
              ├── PostgreSQL: SELECT post + JOIN tags
              ├── UPDATE posts SET views = views + 1
              ├── cache_set(key, post, ttl=300)
              └── 返回 JSON
```

**特殊设计**：即使缓存命中，也会 UPDATE 浏览量计数到 PostgreSQL。
这保证了：
- **文章内容**从缓存读取（快）
- **浏览量统计**始终准确写入数据库

### 3. 标签列表

**路由**：`GET /api/tags`  
**缓存键**：`tags:all`  
**TTL**：300 秒

```
请求 → cache_get("tags:all")
         ├── 命中 → 返回 [{name, post_count}, ...]
         └── 未命中 → PostgreSQL: SELECT tags JOIN post_tags
                    → cache_set → 返回
```

**说明**：标签数量通常很少变化，300 秒缓存可以大幅减少这个聚合查询的开销。

### 4. GitHub 项目列表

**路由**：`GET /api/projects`  
**缓存键**：`projects:all`  
**TTL**：300 秒

```
读取：cache_get("projects:all") → 命中/未命中同上
同步：POST /api/projects/sync → 完成后 cache_delete("projects:*")
```

**说明**：项目同步后会主动清除缓存，下次请求重新从数据库加载最新数据。

### 5. Admin 统计面板

**路由**：`GET /api/admin/stats`  
**缓存键**：`stats:overview`  
**TTL**：60 秒

这是最复杂的查询，包含 8 条 SQL 语句：
- 访客总数、点击总数、消息总数、PV 总数、文章数
- 最近 30 天每日访客趋势
- 最近 30 天每日 PV 趋势
- 热门点击 Top 15
- 热门页面 Top 10（含平均停留时间）
- 邮箱域名分布 Top 15
- 设备类型分布
- 最近消息 Top 10
- 热门文章 Top 10

**TTL 60 秒的原因**：Admin 需要看到接近实时的数据，但这些查询开销大，
60 秒缓存是在"实时性"和"性能"之间的平衡。

**额外机制**：当有新访客提交消息（`POST /api/contact`）时，会主动 `cache_delete("stats:*")`，
保证 Admin 立即看到新消息。

### 6. 留存分析

**路由**：`GET /api/admin/retention`  
**缓存键**：`stats:retention`  
**TTL**：300 秒

```
请求 → cache_get("stats:retention")
         ├── 命中 → 返回留存表
         └── 未命中 → PostgreSQL: CTE 查询（first_visit + daily_activity）
                    → cache_set → 返回
```

**说明**：留存分析是最耗时的查询（多表 CTE + 大量 DISTINCT 计算），300 秒缓存在此非常必要。

---

## 缓存失效策略

| 触发事件 | 清除的缓存 | 清除方式 |
|---|---|---|
| 新消息提交 (`POST /api/contact`) | `stats:*` | `cache_delete("stats:*")` |
| GitHub 项目同步 (`POST /api/projects/sync`) | `projects:*` | `cache_delete("projects:*")` |
| 任何缓存到达 TTL | 该 key 自身 | Redis 自动过期删除 |

> 本项目**不存在**手动清除博客缓存的接口——博客文章内容通过 TTL 自然过期。
> 如果需要立即更新某篇文章的缓存，可以在 Azure Redis 控制台手动执行 `DEL post:<slug>`。

---

## 容错设计

Redis 在本项目中是**可选组件**，不会因为 Redis 故障导致网站崩溃：

```python
# 启动时：连接失败 → redis_client 设为 None
redis_client = None
if REDIS_URL:
    try:
        redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
    except Exception:
        redis_client = None   # 降级：所有请求直接查 PostgreSQL

# 运行时：每个操作都有 try/except
def cache_get(key):
    if redis_client:        # Redis 不可用？跳过
        try:
            val = redis_client.get(key)
            return json.loads(val) if val else None
        except Exception:   # 读取失败？返回 None，当作未命中
            return None
    return None
```

**降级行为**：
| 场景 | Redis 正常 | Redis 不可用 |
|---|---|---|
| `cache_get()` | 返回缓存数据 | 返回 `None`（→ 查数据库） |
| `cache_set()` | 写入缓存 | 静默跳过 |
| `cache_delete()` | 删除缓存 | 静默跳过 |
| 网站功能 | 正常 + 加速 | 正常但稍慢 |

---

## Azure 门户监控

### 关键指标说明

打开 Azure Portal → `aimee-cache` → **监视 → 指标 (Metrics)**

| 指标名称 | 含义 | 正常范围 |
|---|---|---|
| **Cache Hits** | `GET` 命令命中缓存的次数 | 应远大于 Misses |
| **Cache Misses** | `GET` 命令未命中（key 不存在或已过期） | 首次访问/过期后产生 |
| **Cache Hit Rate** | Hits / (Hits + Misses) × 100% | 目标 > 80% |
| **Connected Clients** | 当前保持连接的客户端数 | 通常 1-5（gunicorn workers） |
| **Used Memory / Used Memory RSS** | 已用缓存内存 | 本项目数据量小，通常 < 1MB |
| **Total Keys** | 当前存储的 key 数量 | 取决于页面种类，约 5-20 个 |
| **Evicted Keys** | 因内存满被淘汰的 key 数 | 应该是 0（Basic 250MB 够用） |
| **Expired Keys** | TTL 到期被自动删除的 key | 正常现象，数值越高说明缓存周转活跃 |
| **Get Commands** | GET 命令总次数 | 对应 `cache_get()` 调用 |
| **Set Commands** | SET 命令总次数 | 对应 `cache_set()` 调用 |
| **Total Commands Processed** | 所有命令总次数 | GET + SET + DEL + PING + ... |
| **Server Load** | Redis 服务器 CPU 使用率 | 应 < 70%，Basic SKU 单核 |
| **Cache Latency** | 命令平均延迟 | 目标 < 1ms |

### 如何设置 Metrics 图表

1. Azure Portal → `aimee-cache` → 左侧 **监视 → 指标**
2. 点击 **+ 添加指标**
3. 推荐创建以下图表：

**图表 1：缓存命中率**
- 指标：`Cache Hits`（聚合：Sum）
- 点击"添加指标"，再加 `Cache Misses`（聚合：Sum）
- 时间范围：过去 1 小时
- 用途：观察缓存是否在工作

**图表 2：命令量**
- 指标：`Get Commands` + `Set Commands`
- 时间范围：过去 24 小时
- 用途：了解缓存读写频率

**图表 3：健康状态**
- 指标：`Connected Clients` + `Server Load`
- 时间范围：过去 24 小时
- 用途：确保 Redis 运行正常

**图表 4：内存使用**
- 指标：`Used Memory`
- 时间范围：过去 7 天
- 用途：监控内存增长趋势

### 告警配置建议

Azure Portal → `aimee-cache` → **监视 → 警报 → + 创建警报规则**

| 告警 | 条件 | 建议值 |
|---|---|---|
| Redis 过载 | Server Load > 80% 持续 5 分钟 | 严重 |
| 连接丢失 | Connected Clients = 0 持续 5 分钟 | 严重 |
| 内存接近满 | Used Memory > 200MB | 警告（Basic SKU 上限 250MB） |
| Key 被淘汰 | Evicted Keys > 0 | 警告（说明内存不够） |

---

## 控制台命令测试

### 打开控制台

Azure Portal → `aimee-cache` → 左侧 **控制台 (Console)**

### 常用命令

```redis
# ────── 查看状态 ──────

DBSIZE                          # 当前 key 总数
KEYS *                          # 列出所有 key（生产慎用）
INFO stats                      # 查看命中/未命中统计
INFO memory                     # 内存使用情况

# ────── 查看具体缓存 ──────

GET posts:list::1:10            # 博客列表（默认首页）
GET post:azure-openai-service-troubleshooting-guide   # 某篇文章
GET tags:all                    # 所有标签
GET projects:all                # GitHub 项目列表
GET stats:overview              # Admin 统计
GET stats:retention             # 留存分析

# ────── 查看过期时间 ──────

TTL posts:list::1:10            # 剩余秒数（-2 = 已过期/不存在）
TTL stats:overview              # 统计缓存剩余时间

# ────── 手动管理 ──────

DEL post:azure-openai-service-troubleshooting-guide  # 删除某篇文章缓存
DEL stats:overview              # 删除统计缓存，下次请求重新计算

# ────── 监控实时命令 ──────

MONITOR                         # 实时显示所有 Redis 命令（调试用，按 Ctrl+C 停止）
```

### 完整测试流程

以下步骤可验证 Redis 缓存是否正常工作：

**Step 1：确认初始状态**
```redis
DBSIZE
# 结果：(integer) 0   ← 如果刚重启，或所有 key 已过期
```

**Step 2：触发缓存写入**

在浏览器访问 `https://aimeelan.azurewebsites.net/api/posts`

**Step 3：验证缓存已写入**
```redis
DBSIZE
# 结果：(integer) 1   ← 增加了

KEYS *
# 结果：1) "posts:list::1:10"

GET posts:list::1:10
# 结果：{"posts": [...], "total": 5, "page": 1, "per_page": 10}

TTL posts:list::1:10
# 结果：(integer) 118   ← 还剩 118 秒过期
```

**Step 4：验证缓存命中**

再次访问 `https://aimeelan.azurewebsites.net/api/posts`（相同参数）

```redis
INFO stats
# 找到这两行：
# keyspace_hits:2      ← GET 命中次数（第二次访问命中了缓存）
# keyspace_misses:1    ← GET 未命中次数（第一次访问未命中）
```

**Step 5：等待过期**

等 120 秒后：
```redis
GET posts:list::1:10
# 结果：(nil)   ← 已自动过期

TTL posts:list::1:10
# 结果：(integer) -2   ← key 不存在
```

**Step 6：测试主动失效**

```redis
# 先触发一些缓存
# 浏览器访问 /api/posts, /api/tags, /api/admin/stats

KEYS *
# 结果：1) "posts:list::1:10"
#        2) "tags:all"
#        3) "stats:overview"

# 模拟 cache_delete("stats:*")
SCAN 0 MATCH stats:*
# 结果显示匹配的 key
DEL stats:overview
# 结果：(integer) 1

KEYS *
# stats:overview 已被删除
```

**Step 7：实时监控（MONITOR）**

```redis
MONITOR
```

然后在另一个浏览器标签页访问你的网站，控制台会实时显示：
```
1710000000.123456 [0 172.x.x.x:xxxxx] "GET" "posts:list::1:10"
1710000000.234567 [0 172.x.x.x:xxxxx] "SETEX" "posts:list::1:10" "120" "{\"posts\":...}"
```

按 Ctrl+C 停止 MONITOR。

---

## 性能对比

| 场景 | 无 Redis（直接查 DB） | 有 Redis |
|---|---|---|
| 博客列表请求 | 每次 2 条 SQL（查询 + 计数） | 首次查 DB，后续 120s 内 0 条 SQL |
| 单篇文章请求 | 每次 3 条 SQL | 首次 3 条，后续仅 1 条 `UPDATE views` |
| Admin 统计面板 | 每次 8 条复杂 SQL | 首次 8 条，后续 60s 内 0 条 |
| 留存分析 | 每次 1 条重型 CTE | 首次 1 条，后续 300s 内 0 条 |
| 10 人同时访问博客 | 10 × 2 = 20 条 SQL | 1 × 2 + 0 = 2 条 SQL |
| 响应延迟 | ~50-100ms | 首次 ~50ms，后续 ~1ms |

---

## FAQ

**Q：Redis 挂了网站会崩吗？**  
A：不会。所有缓存操作都有 try/except 保护，Redis 不可用时自动降级为每次直接查 PostgreSQL。

**Q：我改了一篇博客内容，缓存怎么更新？**  
A：目前没有"编辑文章"的 API，所以不存在这个问题。如果未来新增了编辑功能，
需要在保存时调用 `cache_delete("post:*")` 和 `cache_delete("posts:list:*")`。
紧急情况下可以在 Azure Redis 控制台执行 `DEL post:<slug>`。

**Q：Basic SKU 够用吗？**  
A：对于当前体量（5 篇文章、少量项目），Basic SKU（250MB、单核）绰绰有余。
所有缓存数据加起来不超过 1MB。当日均 PV 超过 10,000 时再考虑升级 Standard。

**Q：缓存的数据安全吗？**  
A：Azure Redis 通过 SSL（端口 6380）加密传输，密码认证，且在 Azure 内网中，外部无法直接访问。

**Q：为什么有些 API 没有缓存？**  
A：`/api/verify`、`/api/track`、`/api/contact` 等写操作 API 不需要缓存。
`/api/admin/visitors` 和 `/api/admin/export` 因为带分页/筛选且频率低，也未缓存。
