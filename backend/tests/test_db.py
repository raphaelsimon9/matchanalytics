import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tests.test_model import synth


@pytest.fixture(params=["sqlite", "postgres"])
def backend(request, tmp_path, monkeypatch):
    if request.param == "sqlite":
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    else:
        url = os.getenv("TEST_DATABASE_URL")
        if not url:
            pytest.skip("set TEST_DATABASE_URL to also test Postgres")
        monkeypatch.setenv("DATABASE_URL", url)
    return request.param


def test_log_settle_and_performance(backend, monkeypatch):
    from app import db, providers
    from app import odds as oddsmod
    from app.main import app

    with db.conn() as c:
        c.execute("DELETE FROM picks")  # clean slate (matters for a shared Postgres test DB)

    hist = [{**m, "id": i} for i, m in enumerate(synth())]
    future = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async def fin(comp): return hist
    async def up(comp, days): return [{"id": 999, "kickoff": future, "home": "Strong FC", "away": "Weak FC"}]
    async def gather(comp): return {}, []
    monkeypatch.setattr(providers, "finished_matches", fin)
    monkeypatch.setattr(providers, "upcoming", up)
    monkeypatch.setattr(oddsmod, "gather", gather)

    c = TestClient(app)
    assert c.get("/api/health").json()["db"] == backend
    assert c.get("/api/health/db").status_code == 200
    assert c.get("/api/predictions?competition=PL").status_code == 200
    assert c.get("/api/predictions?competition=PL").status_code == 200  # idempotent
    with db.conn() as k:
        assert k.all("SELECT count(*) AS n FROM picks")[0]["n"] == 9

    perf = c.get("/api/performance").json()
    assert perf["pending"] == 9 and perf["markets"][0]["n"] == 0  # not played yet

    with db.conn() as k:
        k.execute("UPDATE picks SET kickoff='2020-01-01T00:00:00Z'")
    hist.append({"id": 999, "date": "2020-01-01", "home": "Strong FC", "away": "Weak FC", "hg": 3, "ag": 0})
    perf = c.get("/api/performance").json()
    by = {m["key"]: m for m in perf["markets"]}
    assert by["over15"]["hits"] == 1 and by["over25"]["hits"] == 1
    assert by["under25"]["hits"] == 0 and by["btts_yes"]["hits"] == 0 and by["home"]["hits"] == 1
    assert perf["pending"] == 0 and by["over15"]["brier"] is not None
    assert len(perf["recent"]) >= 2
