"""Football data: results + fixtures from football-data.org. (Odds live in app/odds.py.)"""
import time
from datetime import date, timedelta

import httpx

from . import config

FD = "https://api.football-data.org/v4"
COMPETITIONS = {
    "PL": "Premier League", "PD": "La Liga", "SA": "Serie A",
    "BL1": "Bundesliga", "FL1": "Ligue 1", "CL": "Champions League",
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
    if not config.FOOTBALL_DATA_KEY:
        raise RuntimeError("FOOTBALL_DATA_KEY is not set")
    async with httpx.AsyncClient(timeout=25) as c:
        r = await c.get(f"{FD}{path}", params=params, headers={"X-Auth-Token": config.FOOTBALL_DATA_KEY})
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
