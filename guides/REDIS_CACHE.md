# Redis Cache 说明

## 缓存策略

本项目使用 Azure Cache for Redis 缓存热点数据，减少数据库查询压力。

### 缓存键说明

| 缓存键 | 用途 | TTL（过期时间） |
|---------|------|-----------------|
| `stats:overview` | 管理面板统计数据 | 60 秒 |
| `stats:retention` | 用户留存分析 | 300 秒 |
| `posts:list:*` | 博客列表（支持标签/分页） | 120 秒 |
| `post:<slug>` | 单篇博客内容 | 300 秒 |
| `tags:all` | 标签列表及计数 | 300 秒 |
| `projects:all` | GitHub 项目列表 | 300 秒 |

### Admin 面板 Redis 指标

| 指标 | 含义 |
|------|------|
| **Status** | Redis 连接状态（Connected / Not Connected） |
| **Memory Used** | Redis 当前使用的内存 |
| **Peak Memory** | Redis 启动以来的内存峰值 |
| **Total Keys** | Redis 中当前存储的缓存键数量 |

### 关于 Total Keys 为 0

Total Keys 显示 **0** 是正常现象。原因：

1. 缓存键只有在用户访问对应页面时才会被创建
2. 每个缓存键都有较短的 TTL（60-300 秒），过期后自动删除
3. 在没有活跃访问时，所有键都会过期，Total Keys 归零

当有用户浏览网站时，Total Keys 会短暂上升（通常 1-6 个），随后随着 TTL 到期逐渐回到 0。

## 认证方式

Redis 采用双重认证机制，确保连接稳定性：

1. **Access Key 认证**（首选）— 使用 Redis 访问密钥直接连接
2. **Managed Identity + Entra ID 认证**（备用）— 当 Azure Policy 禁用 Access Key 时，自动切换为托管标识 + Entra ID 令牌认证

这种双路认证设计可以避免 Azure Policy 反复禁用 Access Key 导致的连接中断问题。
