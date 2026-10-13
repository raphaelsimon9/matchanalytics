import random
from datetime import date, timedelta

from app.model import TeamModel, form
from app.service import kelly_pct


def synth():
    random.seed(1)
    teams = ["Strong FC", "Mid FC", "Weak FC", "Other FC"]
    skill = {"Strong FC": 2.2, "Mid FC": 1.3, "Weak FC": 0.6, "Other FC": 1.2}
    out, d = [], date.today() - timedelta(days=200)
    for _ in range(25):
        for h in teams:
            for a in teams:
                if h == a: continue
                d += timedelta(days=0)
                out.append({"date": (date.today() - timedelta(days=random.randint(1, 180))).isoformat(),
                            "home": h, "away": a,
                            "hg": max(0, round(random.gauss(skill[h] * 0.9, 1))),
                            "ag": max(0, round(random.gauss(skill[a] * 0.7, 1)))})
    return out


def test_probabilities_are_coherent():
    m = TeamModel(synth())
    p = m.predict("Strong FC", "Weak FC")
    assert abs(p["home"] + p["draw"] + p["away"] - 1) < 1e-6
    assert p["home"] > p["away"] and p["home"] > 0.5
    assert abs(p["over25"] + p["under25"] - 1) < 1e-6


def test_unknown_team_falls_back_to_league_average():
    p = TeamModel(synth()).predict("Nobody", "Ghost")
    assert 0.2 < p["draw"] < 0.4


def test_form_and_kelly():
    assert len(form(synth(), "Strong FC")["last5"]) == 5
    assert kelly_pct(0.5, 2.5) <= 0.02
    assert kelly_pct(0.3, 2.0) == 0.0
