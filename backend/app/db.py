"""Results log: every prediction is saved before kickoff, then settled after the match.

Uses Postgres when DATABASE_URL is set (deployment), otherwise a local SQLite file (DB_PATH)."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

TS = "%Y-%m-%dT%H:%M:%SZ"

SCHEMA = """
CREATE TABLE IF NOT EXISTS picks (
  match_id INTEGER NOT NULL, key TEXT NOT NULL, competition TEXT NOT NULL,
  kickoff TEXT NOT NULL, home TEXT NOT NULL, away TEXT NOT NULL,
  market TEXT NOT NULL, pick TEXT NOT NULL, prob DOUBLE PRECISION NOT NULL, odds DOUBLE PRECISION,
  recommended INTEGER NOT NULL DEFAULT 0, logged_at TEXT NOT NULL,
  result INTEGER, hg INTEGER, ag INTEGER, settled_at TEXT,
  PRIMARY KEY (match_id, key)
)
"""

OUTCOMES = {
    "home": lambda h, a: h > a, "draw": lambda h, a: h == a, "away": lambda h, a: h < a,
    "over15": lambda h, a: h + a > 1, "over25": lambda h, a: h + a > 2,
    "under15": lambda h, a: h + a < 2,
    "under25": lambda h, a: h + a < 3,
    "btts_yes": lambda h, a: h > 0 and a > 0, "btts_no": lambda h, a: h == 0 or a == 0,
}
ORDER = ["over15", "under15", "over25", "under25", "home", "draw", "away", "btts_yes", "btts_no"]

_pg_ready: set = set()


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    return url.replace("postgres://", "postgresql://", 1) if url.startswith("postgres://") else url


def backend() -> str:
    return "postgres" if _database_url() else "sqlite"


class _Conn:
    """Tiny wrapper so the same SQL (written with ? placeholders) runs on SQLite and Postgres."""
    def __init__(self, raw, pg: bool):
        self.raw, self.pg = raw, pg

    def execute(self, sql: str, params=()):
        return self.raw.execute(sql.replace("?", "%s") if self.pg else sql, params)

    def all(self, sql: str, params=()) -> list[dict]:
        rows = self.execute(sql, params).fetchall()
        return rows if self.pg else [dict(r) for r in rows]


@contextmanager
def conn():
    url = _database_url()
    if url:
        import psycopg
        from psycopg.rows import dict_row
        # prepare_threshold=None: safe behind pooled connections (Neon/Supabase poolers)
        raw = psycopg.connect(url, row_factory=dict_row, connect_timeout=15, prepare_threshold=None)
        if url not in _pg_ready:
            raw.execute(SCHEMA)
            raw.commit()
            _pg_ready.add(url)
        c = _Conn(raw, True)
    else:
        raw = sqlite3.connect(os.getenv("DB_PATH", "edgelab.db"))
        raw.row_factory = sqlite3.Row
        raw.execute(SCHEMA)
        c = _Conn(raw, False)
    try:
        yield c
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def ping() -> bool:
    with conn() as c:
        return c.all("SELECT 1 AS ok")[0]["ok"] == 1


def log_predictions(data: dict) -> int:
    """Save/refresh predictions for future matches only (never rewrites a started or settled match)."""
    now = datetime.now(timezone.utc)
    n = 0
    with conn() as c:
        for m in data["matches"]:
            if not m["sample_ok"]:
                continue
            ko = datetime.fromisoformat(m["kickoff"].replace("Z", "+00:00"))
            if ko <= now:
                continue
            rec_key = (m["recommendation"] or {}).get("key")
            for cd in m["candidates"]:
                c.execute(
                    """INSERT INTO picks (match_id,key,competition,kickoff,home,away,market,pick,prob,odds,recommended,logged_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(match_id,key) DO UPDATE SET prob=excluded.prob, odds=excluded.odds,
                         recommended=excluded.recommended, logged_at=excluded.logged_at
                       WHERE picks.result IS NULL""",
                    (m["id"], cd["key"], data["competition"], m["kickoff"], m["home"], m["away"],
                     cd["market"], cd["pick"], cd["prob"], cd["odds"], int(cd["key"] == rec_key),
                     now.strftime(TS)))
                n += 1
    return n


def competitions_pending() -> list[str]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime(TS)
    with conn() as c:
        rows = c.all("SELECT DISTINCT competition FROM picks WHERE result IS NULL AND kickoff < ?", (cutoff,))
    return [r["competition"] for r in rows]


def settle(competition: str, finished: list[dict]) -> int:
    by_id = {m["id"]: m for m in finished if "id" in m}
    now = datetime.now(timezone.utc).strftime(TS)
    n = 0
    with conn() as c:
        rows = c.all("SELECT match_id,key FROM picks WHERE competition=? AND result IS NULL", (competition,))
        for r in rows:
            m = by_id.get(r["match_id"])
            if not m or r["key"] not in OUTCOMES:
                continue
            res = 1 if OUTCOMES[r["key"]](m["hg"], m["ag"]) else 0
            c.execute("UPDATE picks SET result=?, hg=?, ag=?, settled_at=? WHERE match_id=? AND key=?",
                      (res, m["hg"], m["ag"], now, r["match_id"], r["key"]))
            n += 1
    return n


def _stats(rows) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0, "hits": 0, "hit_rate": None, "avg_prob": None, "brier": None, "priced": 0, "roi": None}
    hits = sum(r["result"] for r in rows)
    priced = [r for r in rows if r["odds"]]
    profit = sum((r["odds"] - 1) if r["result"] else -1 for r in priced)
    return {"n": n, "hits": hits, "hit_rate": hits / n,
            "avg_prob": sum(r["prob"] for r in rows) / n,
            "brier": sum((r["prob"] - r["result"]) ** 2 for r in rows) / n,
            "priced": len(priced), "roi": profit / len(priced) if priced else None}


def performance(competition: str | None = None) -> dict:
    where, args = ("WHERE competition=?", (competition,)) if competition else ("", ())
    with conn() as c:
        rows = c.all(f"SELECT * FROM picks {where}", args)
        recent = c.all(
            f"""SELECT * FROM picks {where + ' AND' if where else 'WHERE'} (recommended=1 OR key IN ('over15','over25'))
                ORDER BY kickoff DESC LIMIT 60""", args)
    settled = [r for r in rows if r["result"] is not None]
    markets = []
    for key in ORDER:
        mine = [r for r in settled if r["key"] == key]
        pending = sum(1 for r in rows if r["key"] == key and r["result"] is None)
        label = next((r["pick"] for r in rows if r["key"] == key), key)
        markets.append({"key": key, "pick": label, "pending": pending, **_stats(mine)})
    return {"markets": markets,
            "recommended": _stats([r for r in settled if r["recommended"]]),
            "pending": sum(1 for r in rows if r["result"] is None),
            "recent": recent}
