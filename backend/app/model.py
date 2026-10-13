"""Poisson goal model with recency weighting, shrinkage and a Dixon-Coles low-score correction."""

import math
from collections import defaultdict
from datetime import date

MAX_GOALS = 8
RHO = -0.08  # Dixon-Coles dependence for low scores


def _pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def _shrunk(goals: float, n: float, league_avg: float, prior: float) -> float:
    """Team rate relative to league average, pulled toward 1.0 when sample is small."""
    if league_avg <= 0:
        return 1.0
    return ((goals + prior * league_avg) / (n + prior)) / league_avg


class TeamModel:
    def __init__(self, matches, today=None, half_life=90.0, prior=6.0):
        today = today or date.today()
        rows, w_sum, hg, ag = [], 0.0, 0.0, 0.0
        for m in matches:
            age = (today - date.fromisoformat(m["date"])).days
            w = 0.5 ** (max(age, 0) / half_life)
            rows.append((m, w))
            w_sum += w
            hg += w * m["hg"]
            ag += w * m["ag"]
        self.avg_home = hg / w_sum if w_sum else 1.45
        self.avg_away = ag / w_sum if w_sum else 1.15
        t = defaultdict(lambda: defaultdict(float))
        self.games = defaultdict(int)
        for m, w in rows:
            h, a = m["home"], m["away"]
            t[h]["hn"] += w
            t[h]["hs"] += w * m["hg"]
            t[h]["hc"] += w * m["ag"]
            t[a]["an"] += w
            t[a]["as"] += w * m["ag"]
            t[a]["ac"] += w * m["hg"]
            self.games[h] += 1
            self.games[a] += 1
        self.att_h, self.def_h, self.att_a, self.def_a = {}, {}, {}, {}
        for team, s in t.items():
            self.att_h[team] = _shrunk(s["hs"], s["hn"], self.avg_home, prior)
            self.def_h[team] = _shrunk(s["hc"], s["hn"], self.avg_away, prior)
            self.att_a[team] = _shrunk(s["as"], s["an"], self.avg_away, prior)
            self.def_a[team] = _shrunk(s["ac"], s["an"], self.avg_home, prior)

    def expected_goals(self, home: str, away: str):
        lh = self.avg_home * self.att_h.get(home, 1.0) * self.def_a.get(away, 1.0)
        la = self.avg_away * self.att_a.get(away, 1.0) * self.def_h.get(home, 1.0)
        return max(lh, 0.05), max(la, 0.05)

    def predict(self, home: str, away: str) -> dict:
        lh, la = self.expected_goals(home, away)
        grid = {}
        for i in range(MAX_GOALS + 1):
            for j in range(MAX_GOALS + 1):
                p = _pmf(i, lh) * _pmf(j, la)
                if i == 0 and j == 0:
                    p *= 1 - lh * la * RHO
                elif i == 0 and j == 1:
                    p *= 1 + lh * RHO
                elif i == 1 and j == 0:
                    p *= 1 + la * RHO
                elif i == 1 and j == 1:
                    p *= 1 - RHO
                grid[(i, j)] = max(p, 0.0)
        total = sum(grid.values())
        grid = {k: v / total for k, v in grid.items()}
        home_w = sum(p for (i, j), p in grid.items() if i > j)
        draw = sum(p for (i, j), p in grid.items() if i == j)
        away_w = sum(p for (i, j), p in grid.items() if i < j)
        over15 = sum(p for (i, j), p in grid.items() if i + j > 1)
        over25 = sum(p for (i, j), p in grid.items() if i + j > 2)
        btts = sum(p for (i, j), p in grid.items() if i > 0 and j > 0)
        top = sorted(grid.items(), key=lambda kv: -kv[1])[:3]
        return {
            "xg_home": round(lh, 2),
            "xg_away": round(la, 2),
            "home": home_w,
            "draw": draw,
            "away": away_w,
            "over15": over15,
            "under15": 1 - over15,
            "over25": over25,
            "under25": 1 - over25,
            "btts_yes": btts,
            "btts_no": 1 - btts,
            "top_scores": [{"score": f"{i}-{j}", "p": round(p, 3)} for (i, j), p in top],
        }


def form(matches, team: str, n: int = 5) -> dict:
    played = sorted(
        (m for m in matches if team in (m["home"], m["away"])), key=lambda m: m["date"]
    )[-n:]
    letters, gf, ga = [], 0, 0
    for m in played:
        mine, theirs = (m["hg"], m["ag"]) if m["home"] == team else (m["ag"], m["hg"])
        gf += mine
        ga += theirs
        letters.append("W" if mine > theirs else "D" if mine == theirs else "L")
    k = max(len(played), 1)
    return {
        "last5": "".join(letters),
        "gf_avg": round(gf / k, 2),
        "ga_avg": round(ga / k, 2),
    }
