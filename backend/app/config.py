import os

try:  # optional: lets a local backend/.env file work if python-dotenv is installed
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _list(name: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, "").split(",") if x.strip()]


FOOTBALL_DATA_KEY = os.getenv("FOOTBALL_DATA_KEY", "")   # football-data.org (results + fixtures)
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
MAX_STAKE_PCT = float(os.getenv("MAX_STAKE_PCT", "0.02"))  # hard cap per bet as % of bankroll

# ---- odds providers (each is optional; any combination works) ----
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")             # the-odds-api.com
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")     # api-sports.io (API-Football)
ODDSAPIIO_KEY = os.getenv("ODDSAPIIO_KEY", "")           # odds-api.io (paid; has SportyBet + Stake)
ODDSAPIIO_BOOKMAKERS = os.getenv("ODDSAPIIO_BOOKMAKERS", "SportyBet,Stake")
ODDS_PROVIDERS = _list("ODDS_PROVIDERS")                 # optional allow-list: theoddsapi,apifootball,oddsapiio
PREFERRED_BOOKMAKERS = [b.lower() for b in _list("PREFERRED_BOOKMAKERS")]  # e.g. SportyBet,Stake
ODDS_CACHE_SECONDS = int(os.getenv("ODDS_CACHE_SECONDS", "21600"))  # 6 hours: protects free quotas
THEODDSAPI_REGIONS = os.getenv("THEODDSAPI_REGIONS", "eu")
THEODDSAPI_MARKETS = os.getenv("THEODDSAPI_MARKETS", "h2h,totals")
