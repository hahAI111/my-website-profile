"""
Blog seed data — loaded by app.py on first startup when the posts table is empty.
Separated from app.py for cleaner code organization.
"""

TAGS = [
    "Azure", "AI", "Python", "Troubleshooting", "DevOps",
    "Machine Learning", "Cloud", "SQL", "Networking", "Career",
]

POSTS = [
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
        "tags": ["Azure", "AI", "Troubleshooting"],
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
        "tags": ["Python", "AI", "Azure", "DevOps"],
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
        "tags": ["SQL", "Azure", "Troubleshooting"],
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
        "tags": ["Azure", "Networking", "Cloud"],
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
        "tags": ["Career", "AI", "Azure"],
    },
]
