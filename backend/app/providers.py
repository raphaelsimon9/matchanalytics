"""Data providers: football-data.org (results + fixtures) and The Odds API (odds, optional)."""
import difflib
import re
import time
from datetime import date, timedelta

import httpx

from .config import FOOTBALL_DATA_KEY, ODDS_API_KEY

FD = "https://api.football-data.org/v4"
COMPETITIONS = {
    "PL": "Premier League", "PD": "La Liga", "SA": "Serie A",
    "BL1": "Bundesliga", "FL1": "Ligue 1", "CL": "Champions League",
}
ODDS_SPORT_KEYS = {
    "PL": "soccer_epl", "PD": "soccer_spain_la_liga", "SA": "soccer_italy_serie_a",
    "BL1": "soccer_germany_bundesliga", "FL1": "soccer_france_ligue_one",
    "CL": "soccer_uefa_champs_league",
}
_cache: dict = {}


async def cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = await fn()
    _cache[key] = (time.time(), val)
    return val


async def _fd(path, params=None):
    if not FOOTBALL_DATA_KEY:
        raise RuntimeError("FOOTBALL_DATA_KEY is not set")
    async with httpx.AsyncClient(timeout=25) as c:
        r = await c.get(f"{FD}{path}", params=params, headers={"X-Auth-Token": FOOTBALL_DATA_KEY})
        r.raise_for_status()
        return r.json()


async def finished_matches(comp: str):
    """Current + previous season so early-season predictions are not starved of data."""
    async def go():
        today = date.today()
        cur = today.year if today.month >= 8 else today.year - 1
        out = []
        for season in (cur - 1, cur):
            data = await _fd(f"/competitions/{comp}/matches", {"status": "FINISHED", "season": season})
            for m in data["matches"]:
                ft = m["score"]["fullTime"]
                if ft["home"] is None:
                    continue
                out.append({"id": m["id"], "date": m["utcDate"][:10], "home": m["homeTeam"]["name"],
                            "away": m["awayTeam"]["name"], "hg": ft["home"], "ag": ft["away"]})
        return out
    return await cached(f"fin:{comp}", 3600, go)


async def upcoming(comp: str, days: int):
    async def go():
        d0, d1 = date.today(), date.today() + timedelta(days=days)
        data = await _fd(f"/competitions/{comp}/matches",
                         {"status": "SCHEDULED,TIMED", "dateFrom": d0.isoformat(), "dateTo": d1.isoformat()})
        return [{"id": m["id"], "kickoff": m["utcDate"], "home": m["homeTeam"]["name"],
                 "away": m["awayTeam"]["name"]} for m in data["matches"]]
    return await cached(f"up:{comp}:{days}", 900, go)


def _norm(name: str) -> str:
    n = re.sub(r"\b(fc|afc|cf|ac|as|sc|calcio|ssc|rc|rcd|ud|1\.)\b", "", name.lower())
    return re.sub(r"[^a-z0-9 ]", "", n).strip()


def _same(a: str, b: str) -> bool:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio() >= 0.75


async def odds_events(comp: str):
    if not ODDS_API_KEY or comp not in ODDS_SPORT_KEYS:
        return []
    async def go():
        async with httpx.AsyncClient(timeout=25) as c:
            r = await c.get(f"https://api.the-odds-api.com/v4/sports/{ODDS_SPORT_KEYS[comp]}/odds",
                            params={"apiKey": ODDS_API_KEY, "regions": "eu,uk", "markets": "h2h,totals",
                                    "oddsFormat": "decimal"})
            r.raise_for_status()
            return r.json()
    try:
        return await cached(f"odds:{comp}", 600, go)
    except Exception:
        return []  # odds are optional; predictions still work without them


def best_odds(home: str, away: str, events) -> dict:
    """Best available decimal price per outcome across bookmakers for this fixture."""
    for ev in events:
        if _same(ev["home_team"], home) and _same(ev["away_team"], away):
            best: dict = {}
            def upd(k, price):
                if price > best.get(k, (0, ""))[0]:
                    best[k] = price
            best_map = {}
            for bk in ev.get("bookmakers", []):
                for mk in bk.get("markets", []):
                    for o in mk["outcomes"]:
                        key = None
                        if mk["key"] == "h2h":
                            key = "draw" if o["name"] == "Draw" else ("home" if _same(o["name"], home) else "away")
                        elif mk["key"] == "totals" and o.get("point") in (1.5, 2.5):
                            side = "over" if o["name"] == "Over" else "under"
                            key = f"{side}{'15' if o['point'] == 1.5 else '25'}"
                        if key and o["price"] > best_map.get(key, {}).get("odds", 0):
                            best_map[key] = {"odds": o["price"], "bookmaker": bk["title"]}
            return best_map
    return {}
