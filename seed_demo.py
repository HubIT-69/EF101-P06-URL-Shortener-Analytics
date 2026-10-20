"""Insert clearly labelled, artificial demonstration data for the EF101 project."""
import os
import random
import secrets
import string
import sqlite3
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "url_shortener.db")
ALPHABET = string.ascii_letters + string.digits
random.seed(101)


def stamp(dt):
    return dt.astimezone().isoformat(timespec="seconds")


def main():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")
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
    already = db.execute("SELECT COUNT(*) FROM links WHERE is_demo=1").fetchone()[0]
    if already:
        print(f"Demo data already exists ({already} demo links). No duplicates added.")
        db.close()
        return
    link_ids = []
    now = datetime.now().astimezone()
    for i in range(30):
        code = ''.join(secrets.choice(ALPHABET) for _ in range(6))
        while db.execute("SELECT 1 FROM links WHERE short_code=?", (code,)).fetchone():
            code = ''.join(secrets.choice(ALPHABET) for _ in range(6))
        created = now - timedelta(days=random.randint(0, 28), hours=random.randint(0, 23))
        url = f"https://example.com/demo-page-{i+1}?source=ef101-demo"
        cur = db.execute(
            "INSERT INTO links(original_url, short_code, created_at, is_active, is_demo) VALUES(?,?,?,?,1)",
            (url, code, stamp(created), 0 if i == 29 else 1),
        )
        link_ids.append(cur.lastrowid)
    click_total = 0
    for idx, link_id in enumerate(link_ids):
        # Leave some links at zero clicks to demonstrate that analytics state.
        if idx % 7 == 0:
            continue
        count = random.randint(1, 9)
        for _ in range(count):
            clicked = now - timedelta(days=random.randint(0, 6), hours=random.randint(0, 23), minutes=random.randint(0, 59))
            db.execute("INSERT INTO clicks(link_id, clicked_at) VALUES(?,?)", (link_id, stamp(clicked)))
            click_total += 1
    # Ensure the demo contains at least 100 click events.
    while click_total < 120:
        link_id = random.choice(link_ids[:-1])
        clicked = now - timedelta(days=random.randint(0, 6), hours=random.randint(0, 23))
        db.execute("INSERT INTO clicks(link_id, clicked_at) VALUES(?,?)", (link_id, stamp(clicked)))
        click_total += 1
    db.commit()
    db.close()
    print("Added 30 labelled demo links and at least 120 simulated click events.")
    print("Reminder: these are artificial records for presentation, not real traffic.")


if __name__ == "__main__":
    main()
