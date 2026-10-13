from datetime import datetime

from . import providers
from .config import MAX_STAKE_PCT
from .model import TeamModel, form

MIN_EDGE = 0.03          # model must beat the market price by >=3%
MIN_PROB_VALUE = 0.35    # ignore longshots where model error dominates
MIN_PROB_NO_ODDS = 0.55  # when no odds, only surface strong model favourites
MIN_GAMES = 8            # both teams need a decent sample

LABELS = {
    "home": ("1X2", "Home win"), "draw": ("1X2", "Draw"), "away": ("1X2", "Away win"),
    "over15": ("Goals", "Over 1.5"), "under15": ("Goals", "Under 1.5"),
    "over25": ("Goals", "Over 2.5"), "under25": ("Goals", "Under 2.5"),
    "btts_yes": ("BTTS", "Both teams score"), "btts_no": ("BTTS", "Not both score"),
}


def _confidence(p: float, edge) -> str:
    if edge is not None and edge >= 0.08 and p >= 0.45: return "high"
    if p >= 0.65 or (edge is not None and edge >= 0.05): return "medium"
    return "low"


def kelly_pct(p: float, odds: float) -> float:
    b = odds - 1
    if b <= 0: return 0.0
    k = (p * odds - 1) / b
    return round(max(0.0, min(0.25 * k, MAX_STAKE_PCT)), 4)  # quarter-Kelly, hard capped


async def build_predictions(comp: str, days: int):
    hist = await providers.finished_matches(comp)
    fixtures = await providers.upcoming(comp, days)
    events = await providers.odds_events(comp)
    model = TeamModel(hist)
    out = []
    for f in fixtures:
        pr = model.predict(f["home"], f["away"])
        odds = providers.best_odds(f["home"], f["away"], events)
        cands = []
        for key, (market, pick) in LABELS.items():
            p = pr[key]
            o = odds.get(key)
            edge = round(p * o["odds"] - 1, 3) if o else None
            cands.append({"key": key, "market": market, "pick": pick, "prob": round(p, 3),
                          "fair_odds": round(1 / p, 2) if p > 0 else None,
                          "odds": o["odds"] if o else None, "bookmaker": o["bookmaker"] if o else None,
                          "edge": edge})
        enough = model.games[f["home"]] >= MIN_GAMES and model.games[f["away"]] >= MIN_GAMES
        rec = None
        if enough:
            valued = [c for c in cands if c["edge"] is not None and c["edge"] >= MIN_EDGE and c["prob"] >= MIN_PROB_VALUE]
            if valued:
                rec = max(valued, key=lambda c: c["edge"])
                rec = {**rec, "basis": "value", "stake_pct": kelly_pct(rec["prob"], rec["odds"])}
            elif not odds:
                strong = [c for c in cands if c["prob"] >= MIN_PROB_NO_ODDS]
                if strong:
                    rec = {**max(strong, key=lambda c: c["prob"]), "basis": "model-only", "stake_pct": 0.0}
        if rec:
            rec["confidence"] = _confidence(rec["prob"], rec["edge"])
        out.append({**f, "model": {k: round(v, 3) if isinstance(v, float) else v for k, v in pr.items()},
                    "form_home": form(hist, f["home"]), "form_away": form(hist, f["away"]),
                    "candidates": cands, "recommendation": rec, "sample_ok": enough})
    out.sort(key=lambda x: (x["recommendation"] is None, -(x["recommendation"] or {}).get("edge", 0) if x["recommendation"] and x["recommendation"].get("edge") is not None else 0))
    return {"generated": datetime.utcnow().isoformat() + "Z", "competition": comp,
            "odds_available": bool(events), "matches": out}
