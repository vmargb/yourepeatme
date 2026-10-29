import sqlite3
from datetime import datetime
from pathlib import Path

import scheduler

DB_PATH = Path(__file__).parent / "data" / "study.db"
TABLES = ["problems", "sessions", "session_items", "reviews"]
FIELDS = ("title", "language", "reference_code", "explanation", "tags",
          "importance", "estimated_minutes")
DEFAULTS = dict(language="Python", explanation="", tags="", importance="normal",
                estimated_minutes=5)

SCHEMA = """
CREATE TABLE IF NOT EXISTS problems(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT 'Python',
  reference_code TEXT NOT NULL,
  explanation TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '',
  importance TEXT NOT NULL DEFAULT 'normal' CHECK(importance IN ('low','normal','high')),
  estimated_minutes INTEGER NOT NULL DEFAULT 5 CHECK(estimated_minutes > 0),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  stage INTEGER NOT NULL DEFAULT -1,
  last_reviewed_at TEXT,
  next_review_at TEXT);
CREATE TABLE IF NOT EXISTS sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  budget_minutes INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS session_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  problem_id INTEGER NOT NULL REFERENCES problems(id),
  position INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','done')),
  started_at TEXT,
  UNIQUE(session_id, problem_id));
CREATE TABLE IF NOT EXISTS reviews(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  problem_id INTEGER NOT NULL REFERENCES problems(id),
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  completed_at TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK(outcome IN ('independent','partial','needed_help','could_not_reproduce')),
  attempt_code TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  seconds_spent INTEGER NOT NULL DEFAULT 0,
  UNIQUE(session_id, problem_id));
"""


def now():
    return datetime.now().replace(microsecond=0)


def connect(path=DB_PATH):
    path = str(path)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(SCHEMA)
    return c


def _rows(c, sql, args=()):
    return [dict(r) for r in c.execute(sql, args)]


def list_problems(c, include_archived=False):
    sql = "SELECT * FROM problems" + ("" if include_archived else " WHERE active=1")
    return _rows(c, sql + " ORDER BY title COLLATE NOCASE")


def save_problem(c, data, pid=None):
    d = {**DEFAULTS, **data}
    vals = [d[f] for f in FIELDS]
    t = now().isoformat()
    with c:
        if pid is None:
            marks = ",".join("?" * (len(FIELDS) + 2))
            return c.execute(
                f"INSERT INTO problems({','.join(FIELDS)},created_at,updated_at) VALUES({marks})",
                [*vals, t, t]).lastrowid
        sets = ",".join(f"{f}=?" for f in FIELDS)
        c.execute(f"UPDATE problems SET {sets},updated_at=? WHERE id=?", [*vals, t, pid])
        return pid


def set_active(c, pid, active):
    with c:
        c.execute("UPDATE problems SET active=? WHERE id=?", (int(active), pid))


def create_session(c, budget, problem_ids):
    with c:
        sid = c.execute("INSERT INTO sessions(started_at,budget_minutes) VALUES(?,?)",
                        (now().isoformat(), budget)).lastrowid
        c.executemany("INSERT INTO session_items(session_id,problem_id,position) VALUES(?,?,?)",
                      [(sid, p, i) for i, p in enumerate(problem_ids)])
    return sid


def active_session(c):
    r = c.execute("SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def session_items(c, sid):
    return _rows(c, """SELECT i.*, p.title, p.language, p.reference_code, p.explanation
                       FROM session_items i JOIN problems p ON p.id=i.problem_id
                       WHERE i.session_id=? ORDER BY i.position""", (sid,))


def start_item(c, sid, pid):
    with c:
        c.execute("""UPDATE session_items SET started_at=?
                     WHERE session_id=? AND problem_id=? AND started_at IS NULL""",
                  (now().isoformat(), sid, pid))


def finish_session(c, sid):
    with c:
        c.execute("UPDATE sessions SET ended_at=? WHERE id=? AND ended_at IS NULL",
                  (now().isoformat(), sid))


def session_summary(c, sid):
    r = c.execute("""SELECT COUNT(*) n, COALESCE(SUM(seconds_spent),0) s
                     FROM reviews WHERE session_id=?""", (sid,)).fetchone()
    rem = c.execute("""SELECT COUNT(*) FROM session_items
                       WHERE session_id=? AND status='pending'""", (sid,)).fetchone()[0]
    return dict(completed=r["n"], seconds=r["s"], remaining=rem)


def complete_review(c, sid, pid, outcome, attempt="", notes=""):
    done = now()
    with c:
        c.execute("BEGIN IMMEDIATE")
        item = c.execute("SELECT status, started_at FROM session_items WHERE session_id=? AND problem_id=?",
                         (sid, pid)).fetchone()
        if item is None or item["status"] != "pending":
            raise ValueError("Review already completed or not in session")
        stage = scheduler.next_stage(
            c.execute("SELECT stage FROM problems WHERE id=?", (pid,)).fetchone()["stage"], outcome)
        secs = 0
        if item["started_at"]:
            secs = int((done - datetime.fromisoformat(item["started_at"])).total_seconds())
        c.execute("""INSERT INTO reviews(problem_id,session_id,completed_at,outcome,attempt_code,notes,seconds_spent)
                     VALUES(?,?,?,?,?,?,?)""",
                  (pid, sid, done.isoformat(), outcome, attempt, notes, secs))
        c.execute("UPDATE problems SET stage=?, last_reviewed_at=?, next_review_at=? WHERE id=?",
                  (stage, done.isoformat(), scheduler.next_review(done, stage).isoformat(), pid))
        c.execute("UPDATE session_items SET status='done' WHERE session_id=? AND problem_id=?",
                  (sid, pid))


def export_data(c):
    return {t: _rows(c, f"SELECT * FROM {t}") for t in TABLES}


def import_data(c, data):
    if not isinstance(data, dict) or "problems" not in data:
        raise ValueError("Not a yourepeatme backup")
    with c:
        for t in reversed(TABLES):
            c.execute(f"DELETE FROM {t}")
        for t in TABLES:
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
            for row in data.get(t, []):
                keys = [k for k in cols if k in row]
                c.execute(f"INSERT INTO {t}({','.join(keys)}) VALUES({','.join('?' * len(keys))})",
                          [row[k] for k in keys])
