import csv
import io
import os
import re
import secrets
import sqlite3
import string
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import Flask, abort, flash, redirect, render_template, request, Response, url_for

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "url_shortener.db")
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "local-development-key-change-me")
CODE_LENGTH = 6
CODE_ALPHABET = string.ascii_letters + string.digits


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_url TEXT NOT NULL,
            short_code TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            is_demo INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS clicks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link_id INTEGER NOT NULL,
            clicked_at TEXT NOT NULL,
            FOREIGN KEY(link_id) REFERENCES links(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_clicks_link_id ON clicks(link_id);
        CREATE INDEX IF NOT EXISTS idx_clicks_clicked_at ON clicks(clicked_at);
        """)


def validate_url(value):
    value = (value or "").strip()
    if not value:
        return None, "Please enter a URL."
    parsed = urlparse(value)
    if parsed.scheme.lower() not in ("http", "https"):
        return None, "Only http:// and https:// URLs are supported."
    if not parsed.netloc or "." not in parsed.hostname if parsed.hostname else True:
        return None, "Please enter a valid URL, including a domain such as example.com."
    if any(ch.isspace() for ch in value):
        return None, "URLs cannot contain spaces. Encode spaces in the URL first."
    return value, None


def make_code(db):
    for _ in range(30):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        if not db.execute("SELECT 1 FROM links WHERE short_code = ?", (code,)).fetchone():
            return code
    raise RuntimeError("Could not generate a unique short code. Please try again.")


def click_count(db, link_id):
    row = db.execute("SELECT COUNT(*) AS n FROM clicks WHERE link_id = ?", (link_id,)).fetchone()
    return row["n"]


@app.template_filter("prettydate")
def prettydate(value):
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y, %I:%M %p")
    except ValueError:
        return value


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        original_url, error = validate_url(request.form.get("original_url"))
        if error:
            flash(error, "error")
            return redirect(url_for("index"))
        try:
            with get_db() as db:
                code = make_code(db)
                db.execute(
                    "INSERT INTO links(original_url, short_code, created_at, is_active, is_demo) VALUES(?,?,?,?,0)",
                    (original_url, code, now_iso(), 1),
                )
            flash(f"Short link created: {request.host_url.rstrip('/')}/{code}", "success")
        except sqlite3.Error:
            flash("The link could not be saved. Please try again.", "error")
        return redirect(url_for("index"))

    search = request.args.get("q", "").strip()
    status = request.args.get("status", "all")
    query = """SELECT l.*, COUNT(c.id) AS clicks
               FROM links l LEFT JOIN clicks c ON c.link_id=l.id"""
    clauses, params = [], []
    if search:
        clauses.append("(l.original_url LIKE ? OR l.short_code LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    if status == "active":
        clauses.append("l.is_active=1")
    elif status == "inactive":
        clauses.append("l.is_active=0")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " GROUP BY l.id ORDER BY l.id DESC"
    with get_db() as db:
        links = db.execute(query, params).fetchall()
        total_links = db.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        active_links = db.execute("SELECT COUNT(*) FROM links WHERE is_active=1").fetchone()[0]
        total_clicks = db.execute("SELECT COUNT(*) FROM clicks").fetchone()[0]
        zero_clicks = db.execute("""SELECT COUNT(*) FROM links l
                                  WHERE NOT EXISTS (SELECT 1 FROM clicks c WHERE c.link_id=l.id)""").fetchone()[0]
    return render_template("index.html", links=links, search=search, status=status,
                           total_links=total_links, active_links=active_links,
                           total_clicks=total_clicks, zero_clicks=zero_clicks)


@app.route("/<code>")
def follow(code):
    with get_db() as db:
        link = db.execute("SELECT * FROM links WHERE short_code=?", (code,)).fetchone()
        if not link:
            return render_template("error.html", title="Link not found",
                                   message="This short code does not exist. Check the address and try again."), 404
        if not link["is_active"]:
            return render_template("error.html", title="Link unavailable",
                                   message="This short link has been deactivated by its owner."), 410
        db.execute("INSERT INTO clicks(link_id, clicked_at) VALUES(?,?)", (link["id"], now_iso()))
        target = link["original_url"]
    return redirect(target, code=302)


@app.route("/toggle/<int:link_id>", methods=["POST"])
def toggle_link(link_id):
    with get_db() as db:
        link = db.execute("SELECT id, is_active FROM links WHERE id=?", (link_id,)).fetchone()
        if not link:
            flash("Link not found.", "error")
        else:
            db.execute("UPDATE links SET is_active=? WHERE id=?", (0 if link["is_active"] else 1, link_id))
            flash("Link status updated.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/delete/<int:link_id>", methods=["POST"])
def delete_link(link_id):
    with get_db() as db:
        db.execute("DELETE FROM links WHERE id=?", (link_id,))
    flash("Link deleted.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/analytics")
def analytics():
    with get_db() as db:
        total_links = db.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        total_clicks = db.execute("SELECT COUNT(*) FROM clicks").fetchone()[0]
        top_links = db.execute("""SELECT l.short_code, l.original_url, l.is_active, COUNT(c.id) AS clicks
                                  FROM links l LEFT JOIN clicks c ON c.link_id=l.id
                                  GROUP BY l.id ORDER BY clicks DESC, l.id DESC LIMIT 8""").fetchall()
        zero_clicks = db.execute("""SELECT short_code, original_url FROM links l
                                  WHERE NOT EXISTS (SELECT 1 FROM clicks c WHERE c.link_id=l.id)
                                  ORDER BY l.id DESC LIMIT 10""").fetchall()
        daily = db.execute("""SELECT substr(clicked_at,1,10) AS day, COUNT(*) AS clicks
                              FROM clicks WHERE clicked_at >= ?
                              GROUP BY day ORDER BY day""",
                           ((datetime.now().astimezone() - timedelta(days=6)).date().isoformat(),)).fetchall()
    day_map = {row["day"]: row["clicks"] for row in daily}
    dates = [(datetime.now().astimezone().date() - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    chart_data = [{"day": d[5:], "clicks": day_map.get(d, 0)} for d in dates]
    max_clicks = max([item["clicks"] for item in chart_data] + [1])
    return render_template("analytics.html", total_links=total_links, total_clicks=total_clicks,
                           top_links=top_links, zero_clicks=zero_clicks,
                           chart_data=chart_data, max_clicks=max_clicks)


@app.route("/export.csv")
def export_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Short Code", "Short URL", "Original URL", "Created At", "Active", "Total Clicks", "Last Click"])
    with get_db() as db:
        rows = db.execute("""SELECT l.*, COUNT(c.id) AS clicks, MAX(c.clicked_at) AS last_click
                             FROM links l LEFT JOIN clicks c ON c.link_id=l.id
                             GROUP BY l.id ORDER BY l.id DESC""").fetchall()
        for row in rows:
            writer.writerow([row["short_code"], request.host_url.rstrip("/") + "/" + row["short_code"],
                             row["original_url"], row["created_at"], "Yes" if row["is_active"] else "No",
                             row["clicks"], row["last_click"] or ""])
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=url_analytics.csv"})


@app.route("/health")
def health():
    return {"status": "ok", "application": "URL Shortener with Analytics"}


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
