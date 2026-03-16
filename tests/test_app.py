"""
Unit tests for the portfolio website.
Run with: python -m pytest tests/ -v
"""
import json
import unittest
from unittest.mock import patch, MagicMock

# Patch get_db and init_db before importing app so startup doesn't need a real DB
with patch("psycopg2.connect"), \
     patch.dict("os.environ", {
         "AZURE_POSTGRESQL_CONNECTIONSTRING": "host=localhost dbname=testdb user=test password=test",
         "ADMIN_PASS": "testpass123",
         "SECRET_KEY": "test-secret-key",
     }):
    import app as portfolio_app


class TestEmailValidation(unittest.TestCase):
    """Test the email validation helper."""

    def test_valid_email(self):
        valid, reason = portfolio_app.is_valid_email("user@example.com")
        self.assertTrue(valid)
        self.assertEqual(reason, "OK")

    def test_valid_email_with_dots(self):
        valid, _ = portfolio_app.is_valid_email("first.last@company.co.uk")
        self.assertTrue(valid)

    def test_valid_email_with_plus(self):
        valid, _ = portfolio_app.is_valid_email("user+tag@gmail.com")
        self.assertTrue(valid)

    def test_invalid_email_no_at(self):
        valid, reason = portfolio_app.is_valid_email("notanemail")
        self.assertFalse(valid)
        self.assertIn("Invalid", reason)

    def test_invalid_email_no_domain(self):
        valid, _ = portfolio_app.is_valid_email("user@")
        self.assertFalse(valid)

    def test_invalid_email_empty(self):
        valid, _ = portfolio_app.is_valid_email("")
        self.assertFalse(valid)

    def test_blocked_domain(self):
        valid, reason = portfolio_app.is_valid_email("user@mailinator.com")
        self.assertFalse(valid)
        self.assertIn("blocked", reason.lower())

    def test_blocked_domain_tempmail(self):
        valid, _ = portfolio_app.is_valid_email("user@tempmail.com")
        self.assertFalse(valid)

    def test_allowed_domain(self):
        valid, _ = portfolio_app.is_valid_email("user@microsoft.com")
        self.assertTrue(valid)


class TestHashIp(unittest.TestCase):
    """Test IP hashing helper."""

    def test_deterministic(self):
        h1 = portfolio_app.hash_ip("192.168.1.1")
        h2 = portfolio_app.hash_ip("192.168.1.1")
        self.assertEqual(h1, h2)

    def test_different_ips(self):
        h1 = portfolio_app.hash_ip("192.168.1.1")
        h2 = portfolio_app.hash_ip("10.0.0.1")
        self.assertNotEqual(h1, h2)

    def test_none_ip(self):
        h = portfolio_app.hash_ip(None)
        self.assertIsInstance(h, str)
        self.assertTrue(len(h) > 0)

    def test_hash_length(self):
        h = portfolio_app.hash_ip("127.0.0.1")
        self.assertEqual(len(h), 16)


class TestConnectionParsers(unittest.TestCase):
    """Test PostgreSQL and Redis connection string parsers."""

    def test_pg_conn_standard_format(self):
        raw = "host=myhost dbname=mydb user=me password=secret"
        result = portfolio_app._parse_pg_conn(raw)
        self.assertEqual(result, raw)  # already in standard format

    def test_pg_conn_azure_format(self):
        raw = "Server=myhost.postgres.database.azure.com;Database=mydb;User Id=admin;Password=secret"
        result = portfolio_app._parse_pg_conn(raw)
        self.assertIn("host=myhost.postgres.database.azure.com", result)
        self.assertIn("dbname=mydb", result)
        self.assertIn("user=admin", result)
        self.assertIn("password=secret", result)

    def test_pg_conn_none(self):
        result = portfolio_app._parse_pg_conn(None)
        self.assertIsNone(result)

    def test_pg_conn_empty(self):
        result = portfolio_app._parse_pg_conn("")
        self.assertEqual(result, "")

    def test_redis_conn_standard_format(self):
        raw = "redis://localhost:6379/0"
        result = portfolio_app._parse_redis_conn(raw)
        self.assertEqual(result, {"url": raw})

    def test_redis_conn_azure_format(self):
        raw = "mycache.redis.cache.windows.net:6380,password=abc123,ssl=True,abortConnect=False"
        result = portfolio_app._parse_redis_conn(raw)
        self.assertEqual(result["host"], "mycache.redis.cache.windows.net")
        self.assertEqual(result["port"], 6380)
        self.assertEqual(result["password"], "abc123")
        self.assertTrue(result["ssl"])

    def test_redis_conn_no_ssl(self):
        raw = "localhost:6379,password=test,ssl=False"
        result = portfolio_app._parse_redis_conn(raw)
        self.assertEqual(result["host"], "localhost")
        self.assertFalse(result["ssl"])

    def test_redis_conn_empty(self):
        result = portfolio_app._parse_redis_conn("")
        self.assertIsNone(result)


class TestCacheHelpers(unittest.TestCase):
    """Test cache_get / cache_set with mocked Redis."""

    def test_cache_get_no_redis(self):
        original = portfolio_app.redis_client
        portfolio_app.redis_client = None
        result = portfolio_app.cache_get("anything")
        self.assertIsNone(result)
        portfolio_app.redis_client = original

    def test_cache_set_no_redis(self):
        original = portfolio_app.redis_client
        portfolio_app.redis_client = None
        # Should not raise
        portfolio_app.cache_set("key", {"data": 1})
        portfolio_app.redis_client = original

    def test_cache_roundtrip(self):
        mock_redis = MagicMock()
        stored = {}

        def mock_setex(key, ttl, val):
            stored[key] = val

        def mock_get(key):
            return stored.get(key)

        mock_redis.setex = mock_setex
        mock_redis.get = mock_get

        original = portfolio_app.redis_client
        portfolio_app.redis_client = mock_redis

        portfolio_app.cache_set("test:key", {"hello": "world"}, ttl=60)
        result = portfolio_app.cache_get("test:key")
        self.assertEqual(result, {"hello": "world"})

        portfolio_app.redis_client = original


class TestSeedData(unittest.TestCase):
    """Test that seed_data.py is valid and complete."""

    def test_import_seed_data(self):
        from seed_data import TAGS, POSTS
        self.assertIsInstance(TAGS, list)
        self.assertIsInstance(POSTS, list)

    def test_tags_not_empty(self):
        from seed_data import TAGS
        self.assertGreater(len(TAGS), 0)

    def test_posts_not_empty(self):
        from seed_data import POSTS
        self.assertGreater(len(POSTS), 0)

    def test_post_structure(self):
        from seed_data import POSTS
        required_keys = {"slug", "title", "summary", "content", "tags"}
        for post in POSTS:
            self.assertTrue(required_keys.issubset(post.keys()),
                            f"Post '{post.get('slug', '?')}' missing keys: {required_keys - post.keys()}")

    def test_slugs_unique(self):
        from seed_data import POSTS
        slugs = [p["slug"] for p in POSTS]
        self.assertEqual(len(slugs), len(set(slugs)), "Duplicate slugs found")

    def test_post_tags_exist_in_tags_list(self):
        from seed_data import TAGS, POSTS
        for post in POSTS:
            for tag in post["tags"]:
                self.assertIn(tag, TAGS, f"Tag '{tag}' in post '{post['slug']}' not in TAGS list")


class TestFlaskRoutes(unittest.TestCase):
    """Test Flask route responses (mocking database)."""

    def setUp(self):
        portfolio_app.app.config["TESTING"] = True
        self.client = portfolio_app.app.test_client()

    def test_index_redirects_to_verify(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        # Without session verification, should serve verify.html
        self.assertIn(b"verify", resp.data.lower())

    def test_blog_page_serves_html(self):
        resp = self.client.get("/blog")
        self.assertEqual(resp.status_code, 200)

    def test_projects_page_serves_html(self):
        resp = self.client.get("/projects")
        self.assertEqual(resp.status_code, 200)

    def test_admin_page_serves_html(self):
        resp = self.client.get("/admin")
        self.assertEqual(resp.status_code, 200)

    def test_static_css(self):
        resp = self.client.get("/style.css")
        self.assertEqual(resp.status_code, 200)

    def test_static_js(self):
        resp = self.client.get("/script.js")
        self.assertEqual(resp.status_code, 200)

    def test_verify_missing_fields(self):
        resp = self.client.post("/api/verify",
                                data=json.dumps({"name": "", "email": ""}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_verify_invalid_email(self):
        resp = self.client.post("/api/verify",
                                data=json.dumps({"name": "Test", "email": "notanemail"}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_verify_blocked_email(self):
        resp = self.client.post("/api/verify",
                                data=json.dumps({"name": "Test", "email": "user@mailinator.com"}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data)
        self.assertIn("blocked", data["error"].lower())

    def test_contact_requires_verification(self):
        resp = self.client.post("/api/contact",
                                data=json.dumps({"message": "Hello"}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 403)

    def test_track_requires_verification(self):
        resp = self.client.post("/api/track",
                                data=json.dumps({"element": "btn", "page": "/"}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 403)

    def test_admin_login_missing_credentials(self):
        resp = self.client.post("/api/admin/login",
                                data=json.dumps({"username": "", "password": ""}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_admin_login_wrong_username(self):
        resp = self.client.post("/api/admin/login",
                                data=json.dumps({"username": "hacker", "password": "password"}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 401)

    def test_admin_login_wrong_password(self):
        resp = self.client.post("/api/admin/login",
                                data=json.dumps({"username": "admin", "password": "wrongpass"}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 401)

    @patch.object(portfolio_app, "get_db")
    @patch.dict("os.environ", {"ADMIN_PASS": "testpass123"})
    def test_admin_login_correct(self, mock_get_db):
        """Admin login with correct plain-text password."""
        resp = self.client.post("/api/admin/login",
                                data=json.dumps({"username": "admin", "password": "testpass123"}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data["success"])

    def test_admin_stats_requires_auth(self):
        resp = self.client.get("/api/admin/stats")
        self.assertEqual(resp.status_code, 401)

    @patch.object(portfolio_app, "get_db")
    def test_posts_invalid_page(self, mock_get_db):
        resp = self.client.get("/api/posts?page=abc")
        self.assertEqual(resp.status_code, 400)

    @patch.object(portfolio_app, "get_db")
    def test_posts_invalid_per_page(self, mock_get_db):
        resp = self.client.get("/api/posts?per_page=xyz")
        self.assertEqual(resp.status_code, 400)

    def test_admin_logout(self):
        resp = self.client.post("/api/admin/logout")
        self.assertEqual(resp.status_code, 200)


class TestPageviewAPI(unittest.TestCase):
    """Test pageview tracking."""

    def setUp(self):
        portfolio_app.app.config["TESTING"] = True
        self.client = portfolio_app.app.test_client()

    @patch.object(portfolio_app, "get_db")
    def test_pageview_records(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        resp = self.client.post("/api/pageview",
                                data=json.dumps({"page": "/blog", "referrer": "google.com"}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data["success"])


if __name__ == "__main__":
    unittest.main()
