"""Hand-off layer. There is no official public bet-placement API for Sportybet, Football.com or Stake,
so we do NOT automate logins or bet placement. We build the slip and hand the user off to the site,
where they confirm and place the bet themselves. If a bookmaker gives you partner/affiliate API access,
add an adapter here implementing `Bookmaker`."""
from dotenv import load_dotenv
load_dotenv()
from dataclasses import dataclass
from typing import Protocol


class Bookmaker(Protocol):
    name: str
    def handoff(self, slip: dict) -> dict: ...


@dataclass
class ManualHandoff:
    name: str
    url: str
    note: str = "Open the site, add these selections to your betslip (or load a booking code you created there), review, then confirm yourself."

    def handoff(self, slip: dict) -> dict:
        return {"bookmaker": self.name, "url": self.url, "note": self.note}


REGISTRY = {
    "sportybet": ManualHandoff("Sportybet", "https://www.sportybet.com/ng/"),
    "football.com": ManualHandoff("Football.com", "https://www.football.com/ng/"),
    "stake": ManualHandoff("Stake", "https://stake.com/sports/soccer"),
}
