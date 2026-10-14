# MatchInsights – football match analysis, value-pick recommendations, slip builder

## Run locally
Backend:
    cd backend && python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # add your keys
    export $(grep -v '^#' .env | xargs)
    uvicorn app.main:app --reload
    pytest                 # model tests

Web (also installable as a mobile PWA):
    cd web && cp .env.example .env && npm install && npm run dev

## Keys
- football-data.org free token (results + fixtures): required
- the-odds-api.com key (market odds, enables value/edge picks): optional

## Deploy
- API: Render (render.yaml) or any Docker host. Set env vars, then set CORS_ORIGINS to your web URL.
- Web: Vercel/Netlify, root dir `web`, env VITE_API_URL=https://<your-api-url>

## Results log database
- Local: SQLite file (`DB_PATH`, default `matchinsights.db`). Nothing to set up.
- Deployed: set `DATABASE_URL` to a Postgres connection string (Neon/Supabase free tier). Install with `pip install -r requirements-prod.txt` (Docker does this automatically).
- Verify after deploy: `GET /api/health` shows `"db": "postgres"`, and `GET /api/health/db` returns ok.
- Test against Postgres: `TEST_DATABASE_URL=postgresql://... python -m pytest`

## Odds providers
Set any combination of keys on the server; each one that has a key is used, results are merged, and a failing
provider never breaks the others. The app shows each provider's status (and credits left) above the matches.

| Provider | Env var | Free? | Notes |
|---|---|---|---|
| The Odds API | `ODDS_API_KEY` | 500 credits/month | European bookmakers; usually only the main goals line (2.5) |
| API-Football | `API_FOOTBALL_KEY` | 100 requests/day | Has Over 1.5 and both-teams-to-score odds; prices update about once a day |
| Odds-API.io | `ODDSAPIIO_KEY` | paid | Includes SportyBet and Stake prices (`ODDSAPIIO_BOOKMAKERS`) |

`PREFERRED_BOOKMAKERS` makes the app compare the model against those bookmakers first, and warn when a price
comes from somewhere else. `ODDS_CACHE_SECONDS` limits how often odds are refreshed (default 6 hours).
