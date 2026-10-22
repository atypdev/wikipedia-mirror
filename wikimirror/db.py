"""SQLite storage with FTS5 full-text search."""
import re
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL UNIQUE,
    revid INTEGER,
    timestamp TEXT,
    text TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    title, text, content='pages', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
    INSERT INTO pages_fts(rowid, title, text) VALUES (new.id, new.title, new.text);
END;
CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, title, text) VALUES ('delete', old.id, old.title, old.text);
END;
CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, title, text) VALUES ('delete', old.id, old.title, old.text);
    INSERT INTO pages_fts(rowid, title, text) VALUES (new.id, new.title, new.text);
END;
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS notes_title ON notes(title);
"""


class Mirror:
    def __init__(self, path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    # meta
    def get_meta(self, key, default=None):
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_meta(self, key, value):
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        self.conn.commit()

    # pages
    def upsert_page(self, title, revid, timestamp, text):
        """Insert/replace a page. Returns False when the revision is unchanged."""
        row = self.conn.execute("SELECT revid FROM pages WHERE title=?", (title,)).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO pages(title,revid,timestamp,text) VALUES(?,?,?,?)",
                (title, revid, timestamp, text))
            return True
        if revid is not None and row["revid"] == revid:
            return False
        self.conn.execute(
            "UPDATE pages SET revid=?, timestamp=?, text=? WHERE title=?",
            (revid, timestamp, text, title))
        return True

    def delete_page(self, title):
        return self.conn.execute("DELETE FROM pages WHERE title=?", (title,)).rowcount > 0

    def commit(self):
        self.conn.commit()

    def get_page(self, title):
        r = self.conn.execute("SELECT * FROM pages WHERE title=?", (title,)).fetchone()
        if r is None:  # case-insensitive fallback
            r = self.conn.execute(
                "SELECT * FROM pages WHERE title=? COLLATE NOCASE", (title,)).fetchone()
        return r

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]

    def max_timestamp(self):
        return self.conn.execute("SELECT MAX(timestamp) FROM pages").fetchone()[0]

    def random_page(self):
        return self.conn.execute(
            "SELECT * FROM pages WHERE id >= abs(random()) % "
            "(SELECT MAX(id) FROM pages) + 1 ORDER BY id LIMIT 1").fetchone()

    def search(self, query, limit=10):
        """Ranked full-text search (bm25, title weighted higher) with snippets."""
        match = to_fts_query(query)
        if not match:
            return []
        return self.conn.execute(
            "SELECT p.title, snippet(pages_fts, 1, '[', ']', '…', 12) AS snippet "
            "FROM pages_fts JOIN pages p ON p.id = pages_fts.rowid "
            "WHERE pages_fts MATCH ? ORDER BY bm25(pages_fts, 10.0, 1.0) LIMIT ?",
            (match, limit)).fetchall()

    def title_search(self, prefix, limit=10):
        esc = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return self.conn.execute(
            "SELECT title FROM pages WHERE title LIKE ? ESCAPE '\\' ORDER BY title LIMIT ?",
            (esc + "%", limit)).fetchall()

    # notes
    def add_note(self, title, body):
        cur = self.conn.execute(
            "INSERT INTO notes(title,body,created) VALUES(?,?,?)",
            (title, body, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
        self.conn.commit()
        return cur.lastrowid

    def list_notes(self, title=None):
        if title:
            return self.conn.execute(
                "SELECT * FROM notes WHERE title=? COLLATE NOCASE ORDER BY id", (title,)).fetchall()
        return self.conn.execute("SELECT * FROM notes ORDER BY id").fetchall()

    def delete_note(self, note_id):
        n = self.conn.execute("DELETE FROM notes WHERE id=?", (note_id,)).rowcount
        self.conn.commit()
        return n > 0

    def optimize(self):
        self.conn.execute("INSERT INTO pages_fts(pages_fts) VALUES('optimize')")
        self.conn.commit()


def to_fts_query(q):
    """Turn free text into a safe FTS5 query: quoted terms, prefix on the last."""
    terms = re.findall(r"\w+", q, re.UNICODE)
    if not terms:
        return ""
    parts = ['"%s"' % t for t in terms]
    parts[-1] += "*"
    return " ".join(parts)
