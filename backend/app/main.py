from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import db, providers
from .bookmakers import REGISTRY
from .config import CORS_ORIGINS, MAX_STAKE_PCT
from .service import build_predictions

app = FastAPI(title="EdgeLab API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"ok": True, "db": db.backend()}


@app.get("/api/health/db")
async def health_db():
    """Opens a real database connection – use this to verify DATABASE_URL after deploying."""
    try:
        await run_in_threadpool(db.ping)
        return {"ok": True, "db": db.backend()}
    except Exception as e:
        raise HTTPException(503, f"Database error: {type(e).__name__}: {e}")


@app.get("/api/competitions")
def competitions():
    return providers.COMPETITIONS


@app.get("/api/predictions")
async def predictions(competition: str = Query("PL"), days: int = Query(7, ge=1, le=14)):
    if competition not in providers.COMPETITIONS:
        raise HTTPException(400, "Unsupported competition")
    try:
        result = await build_predictions(competition, days)
        try:
            await run_in_threadpool(db.log_predictions, result)   # results log must never break predictions
        except Exception:
            pass
        return result
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(502, f"Upstream data error: {e}")


class Selection(BaseModel):
    match: str
    market: str
    pick: str
    odds: float = Field(gt=1.0)


class SlipIn(BaseModel):
    selections: list[Selection] = Field(min_length=1, max_length=10)
    stake: float = Field(gt=0)
    bankroll: float | None = Field(default=None, gt=0)


@app.post("/api/slip")
def slip(body: SlipIn):
    combined = 1.0
    for s in body.selections:
        combined *= s.odds
    warnings = []
    if len(body.selections) > 4:
        warnings.append("Long accumulators lose far more often than singles; the bookmaker margin compounds.")
    if body.bankroll and body.stake > body.bankroll * MAX_STAKE_PCT * 2.5:
        warnings.append(f"Stake is above {MAX_STAKE_PCT * 2.5:.0%} of your bankroll. Consider reducing it.")
    if len({s.match for s in body.selections}) < len(body.selections):
        warnings.append("Several picks from the same match are correlated; bookmakers may reject or reprice them.")
    text = "\n".join(f"{i + 1}. {s.match} | {s.pick} @ {s.odds:.2f}" for i, s in enumerate(body.selections))
    text += f"\nCombined odds: {combined:.2f} | Stake: {body.stake:.2f} | Potential return: {body.stake * combined:.2f}"
    return {"combined_odds": round(combined, 2), "potential_return": round(body.stake * combined, 2),
            "warnings": warnings, "text": text,
            "handoff": [b.handoff({}) for b in REGISTRY.values()]}


@app.get("/api/performance")
async def performance(competition: str | None = None):
    """Settle finished matches, then report hit rate / calibration / ROI per market."""
    try:
        pending = await run_in_threadpool(db.competitions_pending)
        for comp in pending:
            try:
                await run_in_threadpool(db.settle, comp, await providers.finished_matches(comp))
            except Exception:
                pass  # try again next time (rate limit, network)
        return await run_in_threadpool(db.performance, competition)
    except Exception as e:
        raise HTTPException(503, f"Results log unavailable: {type(e).__name__}: {e}")
