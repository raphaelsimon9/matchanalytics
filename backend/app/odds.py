"""Pluggable odds providers + merge logic.

Every provider returns {fixture_id: {market_key: [(price, bookmaker), ...]}} where fixture_id is the
football-data.org match id and market_key is one of:
  home, draw, away, over15, under15, over25, under25, btts_yes, btts_no
`gather()` calls every configured provider (cached, failures isolated), merges the offers and picks,
per market, the best price at your PREFERRED_BOOKMAKERS if any quote it, otherwise the best price overall.
"""
import difflib
import os
import re
import time
import unicodedata
from datetime import date, datetime, timedelta

import httpx

from . import config, providers

_quota: dict = {}    # provider name -> credits/requests left (from response headers)
_errors: dict = {}   # (provider slug, comp) -> (timestamp, message): avoids hammering a failing API


# ───────────────────────── team-name matching ─────────────────────────
STOP = {"fc", "afc", "cf", "ac", "as", "sc", "calcio", "ssc", "rc", "rcd", "ud", "the", "and", "1"}
ALIAS = {"man": "manchester", "utd": "united", "nottm": "nottingham", "wolves": "wolverhampton wanderers",
         "spurs": "tottenham hotspur", "psg": "paris saint germain"}


def canon(name: str) -> frozenset:
    s = unicodedata.normalize("NFKD", name.lower().replace("&", " and "))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = []
    for t in s.split():
        toks.extend(ALIAS.get(t, t).split())
    return frozenset(t for t in toks if t not in STOP)


def same(a: str, b: str) -> bool:
    ta, tb = canon(a), canon(b)
    if not ta or not tb:
        return False
    if ta == tb or ta <= tb or tb <= ta:
        return True
    return difflib.SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio() >= 0.82


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def match_fixture(fixtures, home: str, away: str, when: str | None = None):
    for f in fixtures:
        if not (same(f["home"], home) and same(f["away"], away)):
            continue
        if when:
            try:
                if abs((_parse_iso(when) - _parse_iso(f["kickoff"])).total_seconds()) > 36 * 3600:
                    continue
            except ValueError:
                pass
        return f["id"]
    return None


# ───────────────────────── shared helpers ─────────────────────────
def _client(**kw):
    return httpx.AsyncClient(timeout=25, **kw)


def _note_quota(name: str, value):
    try:
        _quota[name] = int(float(value))
    except (TypeError, ValueError):
        pass


def _check(r, name: str):
    if r.status_code >= 400:
        raise RuntimeError(f"{name} HTTP {r.status_code}: {r.text[:200].strip()}")


def _offer(slot: dict, key: str, price, book: str):
    try:
        p = float(price)
    except (TypeError, ValueError):
        return
    if p > 1.0:
        slot.setdefault(key, []).append((p, book))


# ───────────────────────── provider 1: The Odds API ─────────────────────────
THEODDSAPI_SPORTS = {
    "PL": "soccer_epl", "PD": "soccer_spain_la_liga", "SA": "soccer_italy_serie_a",
    "BL1": "soccer_germany_bundesliga", "FL1": "soccer_france_ligue_one", "CL": "soccer_uefa_champs_league",
}


def parse_theoddsapi(events, fixtures) -> dict:
    out: dict = {}
    for ev in events:
        fid = match_fixture(fixtures, ev["home_team"], ev["away_team"], ev.get("commence_time"))
        if fid is None:
            continue
        slot = out.setdefault(fid, {})
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                for o in mk.get("outcomes", []):
                    key = None
                    if mk["key"] == "h2h":
                        if o["name"] == "Draw": key = "draw"
                        elif same(o["name"], ev["home_team"]): key = "home"
                        elif same(o["name"], ev["away_team"]): key = "away"
                    elif mk["key"] == "totals" and o.get("point") in (1.5, 2.5):
                        key = ("over" if o["name"] == "Over" else "under") + ("15" if o["point"] == 1.5 else "25")
                    elif mk["key"] == "btts":
                        key = "btts_yes" if str(o["name"]).lower() == "yes" else "btts_no"
                    if key:
                        _offer(slot, key, o.get("price"), bk.get("title", "?"))
    return out


async def fetch_theoddsapi(comp, fixtures) -> dict:
    sport = THEODDSAPI_SPORTS.get(comp)
    if not sport:
        return {}
    async with _client() as c:
        r = await c.get(f"https://api.the-odds-api.com/v4/sports/{sport}/odds",
                        params={"apiKey": config.ODDS_API_KEY, "regions": config.THEODDSAPI_REGIONS,
                                "markets": config.THEODDSAPI_MARKETS, "oddsFormat": "decimal"})
    _note_quota("The Odds API", r.headers.get("x-requests-remaining"))
    _check(r, "The Odds API")
    return parse_theoddsapi(r.json(), fixtures)


# ───────────────────────── provider 2: API-Football (api-sports.io) ─────────────────────────
AF = "https://v3.football.api-sports.io"
AF_LEAGUES = {"PL": 39, "PD": 140, "SA": 135, "BL1": 78, "FL1": 61, "CL": 2}


def parse_apifootball_item(item: dict, slot: dict):
    for bk in item.get("bookmakers", []):
        book = bk.get("name", "?")
        for bet in bk.get("bets", []):
            name, bid = (bet.get("name") or "").strip().lower(), bet.get("id")
            if bid == 1 or name == "match winner":
                mapping = {"home": "home", "draw": "draw", "away": "away"}
            elif bid == 5 or name in ("goals over/under", "over/under"):
                mapping = {"over 1.5": "over15", "under 1.5": "under15", "over 2.5": "over25", "under 2.5": "under25"}
            elif bid == 8 or name == "both teams score":
                mapping = {"yes": "btts_yes", "no": "btts_no"}
            else:
                continue
            for v in bet.get("values", []):
                key = mapping.get(str(v.get("value", "")).strip().lower())
                if key:
                    _offer(slot, key, v.get("odd"), book)


async def fetch_apifootball(comp, fixtures) -> dict:
    lid = AF_LEAGUES.get(comp)
    if not lid:
        return {}
    today = date.today()
    season = today.year if today.month >= 8 else today.year - 1
    async with _client(headers={"x-apisports-key": config.API_FOOTBALL_KEY}) as c:
        async def get(path, params):
            r = await c.get(AF + path, params=params)
            _note_quota("API-Football", r.headers.get("x-ratelimit-requests-remaining"))
            _check(r, "API-Football")
            j = r.json()
            if j.get("errors"):   # api-sports reports many problems as HTTP 200 + an errors field
                raise RuntimeError(f"API-Football: {j['errors']}")
            return j

        fx = await get("/fixtures", {"league": lid, "season": season,
                                     "from": today.isoformat(), "to": (today + timedelta(days=14)).isoformat()})
        idmap = {}
        for it in fx.get("response", []):
            fid = match_fixture(fixtures, it["teams"]["home"]["name"], it["teams"]["away"]["name"], it["fixture"].get("date"))
            if fid is not None:
                idmap[it["fixture"]["id"]] = fid
        out: dict = {}
        page, total = 1, 1
        while idmap and page <= min(total, 6):   # odds come 10 fixtures per page; cap pages to protect quota
            j = await get("/odds", {"league": lid, "season": season, "page": page})
            total = (j.get("paging") or {}).get("total") or 1
            for it in j.get("response", []):
                fid = idmap.get(it["fixture"]["id"])
                if fid is not None:
                    parse_apifootball_item(it, out.setdefault(fid, {}))
            if len(out) >= len(idmap):
                break
            page += 1
    return out


# ───────────────────────── provider 3: Odds-API.io (paid; has SportyBet + Stake) ─────────────────────────
OIO = "https://api.odds-api.io/v3"
OIO_LEAGUE_NAMES = {"PL": "england - premier league", "PD": "spain - la liga", "SA": "italy - serie a",
                    "BL1": "germany - bundesliga", "FL1": "france - ligue 1"}


def _oio_find_slug(comp: str, leagues: list) -> str | None:
    override = os.getenv(f"ODDSAPIIO_LEAGUE_{comp}")
    if override:
        return override
    target = OIO_LEAGUE_NAMES.get(comp)
    for lg in leagues:
        n = lg.get("name", "").lower()
        if target and n == target:
            return lg["slug"]
        if comp == "CL" and "champions league" in n and not any(x in n for x in ("women", "qualif")):
            return lg["slug"]
    return None


def parse_oddsapiio(arr: list, evmap: dict) -> dict:
    out: dict = {}
    for ev in arr:
        fid = evmap.get(str(ev.get("id")))
        if fid is None:
            continue
        slot = out.setdefault(fid, {})
        for book, markets in (ev.get("bookmakers") or {}).items():
            for m in markets:
                nm = (m.get("name") or "").lower()
                for row in m.get("odds", []):
                    if nm == "ml":
                        for k in ("home", "draw", "away"):
                            _offer(slot, k, row.get(k), book)
                    elif nm == "totals":
                        try:
                            line = float(row.get("hdp"))
                        except (TypeError, ValueError):
                            continue
                        if line in (1.5, 2.5):
                            tag = "15" if line == 1.5 else "25"
                            _offer(slot, "over" + tag, row.get("over"), book)
                            _offer(slot, "under" + tag, row.get("under"), book)
                    elif nm == "both teams to score":
                        _offer(slot, "btts_yes", row.get("yes"), book)
                        _offer(slot, "btts_no", row.get("no"), book)
    return out


async def fetch_oddsapiio(comp, fixtures) -> dict:
    key = config.ODDSAPIIO_KEY
    async with _client() as c:
        async def get(path, params):
            r = await c.get(OIO + path, params={"apiKey": key, **params})
            _note_quota("Odds-API.io", r.headers.get("x-ratelimit-remaining"))
            _check(r, "Odds-API.io")
            return r.json()

        async def leagues():
            return await get("/leagues", {"sport": "football"})
        slug = _oio_find_slug(comp, await providers.cached("oio:leagues", 86400, leagues))
        if not slug:
            raise RuntimeError(f"Odds-API.io: league for {comp} not found; set ODDSAPIIO_LEAGUE_{comp}=<slug>")
        events = await get("/events", {"sport": "football", "league": slug, "status": "pending", "limit": 100})
        evmap = {}
        for e in events:
            fid = match_fixture(fixtures, e["home"], e["away"], e.get("date"))
            if fid is not None:
                evmap[str(e["id"])] = fid
        out: dict = {}
        ids = list(evmap)
        for i in range(0, len(ids), 10):   # /odds/multi: up to 10 events per request = 1 request
            arr = await get("/odds/multi", {"eventIds": ",".join(ids[i:i + 10]),
                                            "bookmakers": config.ODDSAPIIO_BOOKMAKERS,
                                            "markets": "ML,Totals,Both Teams To Score"})
            for fid, keys in parse_oddsapiio(arr, evmap).items():
                for k, offers in keys.items():
                    out.setdefault(fid, {}).setdefault(k, []).extend(offers)
    return out


# ───────────────────────── merge ─────────────────────────
PROVIDERS = {
    "theoddsapi": ("The Odds API", lambda: config.ODDS_API_KEY, fetch_theoddsapi),
    "apifootball": ("API-Football", lambda: config.API_FOOTBALL_KEY, fetch_apifootball),
    "oddsapiio": ("Odds-API.io", lambda: config.ODDSAPIIO_KEY, fetch_oddsapiio),
}


def is_preferred(book: str) -> bool:
    b = book.lower()
    return any(p in b for p in config.PREFERRED_BOOKMAKERS)


def choose(offers: list) -> dict:
    """offers: [(price, bookmaker, provider)]. Prefer the user's bookmakers; else best overall."""
    pref = [o for o in offers if is_preferred(o[1])]
    price, book, src = max(pref or offers, key=lambda o: o[0])
    flag = True if pref else (False if config.PREFERRED_BOOKMAKERS else None)
    return {"odds": price, "bookmaker": book, "source": src, "preferred": flag}


async def gather(comp: str):
    """Returns ({fixture_id: {market_key: {odds, bookmaker, source, preferred}}}, [provider status])."""
    allow = config.ODDS_PROVIDERS or list(PROVIDERS)
    active = [(s, *PROVIDERS[s]) for s in allow if s in PROVIDERS and PROVIDERS[s][1]()]
    if not active:
        return {}, []
    fixtures = await providers.upcoming(comp, 14)
    merged: dict = {}
    status = []
    for slug, name, _key, fetch in active:
        st = {"provider": name, "ok": False, "matched": 0, "error": None, "quota_left": None}
        recent = _errors.get((slug, comp))
        if recent and time.time() - recent[0] < 600:
            st["error"] = recent[1]          # failed recently: do not retry (and burn quota) yet
        else:
            try:
                async def go(fetch=fetch):
                    return await fetch(comp, fixtures)
                data = await providers.cached(f"odds:{slug}:{comp}", config.ODDS_CACHE_SECONDS, go)
                _errors.pop((slug, comp), None)
                st["ok"], st["matched"] = True, len(data)
                for fid, keys in data.items():
                    for k, offers in keys.items():
                        merged.setdefault(fid, {}).setdefault(k, []).extend((p, b, name) for p, b in offers)
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"[:240]
                _errors[(slug, comp)] = (time.time(), msg)
                st["error"] = msg
        st["quota_left"] = _quota.get(name)
        status.append(st)
    return {fid: {k: choose(v) for k, v in keys.items()} for fid, keys in merged.items()}, status
