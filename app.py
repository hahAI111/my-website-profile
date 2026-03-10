import os
import re
import json
import secrets
import hashlib
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, session, redirect
import psycopg2
import psycopg2.extras
import redis

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# ── Configuration ──────────────────────────────────────────
# Azure App Service auto-injects these env vars when you create "Web App + Database"
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "yourname@example.com")
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.example.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "yourname@example.com")
SMTP_PASS = os.environ.get("SMTP_PASS", "your-app-password")

# PostgreSQL connection (Azure auto-sets AZURE_POSTGRESQL_CONNECTIONSTRING)
# Azure Connection Strings become env vars with prefix: CUSTOMCONNSTR_, SQLCONNSTR_, etc.
DATABASE_URL = (
    os.environ.get("AZURE_POSTGRESQL_CONNECTIONSTRING")
    or os.environ.get("CUSTOMCONNSTR_AZURE_POSTGRESQL_CONNECTIONSTRING")
    or "host=localhost dbname=portfoliodb user=postgres password=postgres"
)

# Redis connection (Azure auto-sets AZURE_REDIS_CONNECTIONSTRING)
REDIS_URL = os.environ.get("AZURE_REDIS_CONNECTIONSTRING", "")

# Disposable / suspicious email domains (extend as needed)
BLOCKED_DOMAINS = {
    "tempmail.com", "throwaway.email", "guerrillamail.com",
    "mailinator.com", "yopmail.com", "sharklasers.com",
    "guerrillamailblock.com", "grr.la", "dispostable.com",
    "trashmail.com", "10minutemail.com", "fakeinbox.com",
    "tempail.com", "getnada.com", "maildrop.cc",
}

# ── Redis Cache ────────────────────────────────────────────
redis_client = None
if REDIS_URL:
    try:
        redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
    except Exception:
        redis_client = None

def cache_get(key):
    if redis_client:
        try:
            val = redis_client.get(key)
            return json.loads(val) if val else None
        except Exception:
            return None
    return None

def cache_set(key, value, ttl=300):
    if redis_client:
        try:
            redis_client.setex(key, ttl, json.dumps(value))
        except Exception:
            pass

def cache_delete(pattern):
    if redis_client:
        try:
            for key in redis_client.scan_iter(match=pattern):
                redis_client.delete(key)
        except Exception:
            pass

# ── Database (PostgreSQL) ──────────────────────────────────
def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS visitors (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            verified INTEGER DEFAULT 0,
            token TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS click_logs (
            id SERIAL PRIMARY KEY,
            visitor_id INTEGER REFERENCES visitors(id),
            element TEXT NOT NULL,
            page TEXT,
            clicked_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            visitor_id INTEGER REFERENCES visitors(id),
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            message TEXT NOT NULL,
            sent_at TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

try:
    init_db()
except Exception as e:
    print(f"DB init warning (will retry on first request): {e}")

# ── Helpers ────────────────────────────────────────────────
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

def is_valid_email(email):
    if not EMAIL_RE.match(email):
        return False, "Invalid email format."
    domain = email.split("@")[1].lower()
    if domain in BLOCKED_DOMAINS:
        return False, "Disposable or blocked email domain."
    return True, "OK"

def send_notification(visitor_name, visitor_email, message_text):
    """Send email notification to site owner. Fails silently if SMTP not configured."""
    try:
        body = (
            f"New message from your portfolio site!\n\n"
            f"From: {visitor_name} <{visitor_email}>\n"
            f"Time: {datetime.utcnow().isoformat()}\n\n"
            f"Message:\n{message_text}"
        )
        msg = MIMEText(body)
        msg["Subject"] = f"Portfolio Contact: {visitor_name}"
        msg["From"] = SMTP_USER
        msg["To"] = OWNER_EMAIL
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [OWNER_EMAIL], msg.as_string())
        return True
    except Exception:
        # SMTP not configured yet – that's OK during development
        return False

def require_verified(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("verified"):
            return jsonify({"error": "Not verified"}), 403
        return f(*args, **kwargs)
    return decorated

# ── Static files ───────────────────────────────────────────
@app.route("/")
def index():
    if session.get("verified"):
        return send_from_directory("static", "index.html")
    return send_from_directory("static", "verify.html")

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)

# ── Auth / Verification ───────────────────────────────────
@app.route("/api/verify", methods=["POST"])
def verify_visitor():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()

    if not name or not email:
        return jsonify({"error": "Name and email are required."}), 400

    valid, reason = is_valid_email(email)
    if not valid:
        return jsonify({"error": reason}), 400

    token = secrets.token_urlsafe(32)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO visitors (name, email, verified, token) VALUES (%s, %s, 1, %s) RETURNING id",
        (name, email, token),
    )
    visitor_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()

    session["verified"] = True
    session["visitor_id"] = visitor_id
    session["visitor_name"] = name
    session["visitor_email"] = email

    return jsonify({"success": True, "redirect": "/"})

# ── Click Tracking ─────────────────────────────────────────
@app.route("/api/track", methods=["POST"])
@require_verified
def track_click():
    data = request.get_json()
    element = (data.get("element") or "").strip()
    page = (data.get("page") or "").strip()

    if not element:
        return jsonify({"error": "element is required"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO click_logs (visitor_id, element, page) VALUES (%s, %s, %s)",
        (session.get("visitor_id"), element, page),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})

# ── Contact / Interest ─────────────────────────────────────
@app.route("/api/contact", methods=["POST"])
@require_verified
def contact():
    data = request.get_json()
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"error": "Message is required."}), 400

    visitor_id = session.get("visitor_id")
    name = session.get("visitor_name", "Anonymous")
    email = session.get("visitor_email", "unknown")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (visitor_id, name, email, message) VALUES (%s, %s, %s, %s)",
        (visitor_id, name, email, message),
    )
    conn.commit()
    cur.close()
    conn.close()

    cache_delete("stats:*")
    email_sent = send_notification(name, email, message)

    return jsonify({
        "success": True,
        "email_sent": email_sent,
        "note": "Message saved!" + (" Email sent to owner." if email_sent else " (Email delivery pending – SMTP not configured yet.)")
    })

# ── Admin: view data (for you) ─────────────────────────────
@app.route("/api/admin/stats")
def admin_stats():
    cached = cache_get("stats:overview")
    if cached:
        return jsonify(cached)

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT COUNT(*) as c FROM visitors")
    visitors = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM click_logs")
    clicks = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM messages")
    messages = cur.fetchone()["c"]
    cur.execute("SELECT id, name, email, message, sent_at::text as sent_at FROM messages ORDER BY sent_at DESC LIMIT 10")
    recent = cur.fetchall()
    cur.close()
    conn.close()

    result = {"visitors": visitors, "clicks": clicks, "messages": messages, "recent_messages": recent}
    cache_set("stats:overview", result, ttl=60)
    return jsonify(result)

# ── Run ────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000)
