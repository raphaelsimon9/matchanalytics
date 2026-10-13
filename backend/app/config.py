import os
from dotenv import load_dotenv
load_dotenv()


FOOTBALL_DATA_KEY = os.getenv("FOOTBALL_DATA_KEY", "")   # football-data.org (free tier)
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")             # the-odds-api.com (optional)
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
MAX_STAKE_PCT = float(os.getenv("MAX_STAKE_PCT", "0.02"))  # hard cap per bet as % of bankroll
