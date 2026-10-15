"""Pure fixture normalization and conservative alert eligibility."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
import json

SKU = "10-10446-120"
URL = ("https://www.pokemoncenter.com/product/10-10446-120/"
       "pokemon-tcg-mega-evolution-delta-reign-booster-display-box-36-packs")
MAX_AGE = timedelta(minutes=15)
STATES = {"in_stock", "sold_out", "preorder", "unknown"}


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class Product:
    id: str = "delta-reign-36"
    name: str = "Pokémon TCG: Mega Evolution—Delta Reign Booster Display Box (36 Packs)"
    sku: str = SKU
    packs: int = 36
    source_id: str = "pokemon-center-us"
    url: str = URL
    msrp_cents: int | None = None
    currency: str = "USD"


@dataclass(frozen=True)
class Source:
    id: str = "pokemon-center-us"
    live_enabled: bool = False
    reason: str = "Permitted access and terms unverified; live fetching is not implemented."


PRODUCT = Product()
SOURCE = Source()


class Adapter(Protocol):
    def read(self, raw: str, now: datetime) -> dict: ...


class LiveAdapter:
    def read(self, raw: str, now: datetime) -> dict:
        # No network implementation, even if a caller changes registry metadata.
        raise PermissionError(SOURCE.reason)


class FixtureAdapter:
    def read(self, raw: str, now: datetime) -> dict:
        observation = dict(product_id=PRODUCT.id, source_id=SOURCE.id,
                           mode="fixture", received_at=now.isoformat(),
                           checked_at=None, status="error", availability="unknown",
                           fetch_outcome="malformed", identity_ok=False,
                           fresh=False, price_cents=None, currency=None,
                           purchasable=False, evidence=None, reason="malformed fixture")
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return observation
            observation["evidence"] = data
            checked = timestamp(data["checked_at"])
            observation["checked_at"] = checked.isoformat()
            age = now - checked
            observation["fresh"] = timedelta(0) <= age <= MAX_AGE
            observation["identity_ok"] = (
                data.get("sku") == SKU and data.get("url") == URL
                and type(data.get("packs")) is int and data["packs"] == 36
                and data.get("source_id") == SOURCE.id)
            outcome = data.get("fetch_outcome")
            if outcome not in {"ok", "blocked", "rate_limited", "error"}:
                return observation
            observation["fetch_outcome"] = outcome
            if outcome != "ok":
                observation.update(status=outcome, reason="source access failure")
                return observation
            state = data.get("availability")
            if state not in STATES:
                return observation
            observation["availability"] = state
            price = data.get("price_cents")
            observation["price_cents"] = price if type(price) is int and 0 < price < 10**9 else None
            observation["currency"] = data.get("currency")
            observation["purchasable"] = data.get("purchasable") is True
            if not observation["identity_ok"]:
                observation.update(status="unknown", reason="product identity mismatch")
            elif age < timedelta(0):
                observation.update(status="error", reason="future timestamp")
            elif not observation["fresh"]:
                observation.update(status="stale", reason="observation older than 15 minutes")
            else:
                observation.update(status=state, reason="fixture normalized")
        except (ValueError, TypeError, KeyError, AttributeError):
            pass
        return observation


def eligible(observation: dict, demo_rule: bool) -> tuple[bool, str]:
    if observation["status"] != "in_stock":
        return False, observation["reason"]
    if not observation["identity_ok"] or not observation["fresh"]:
        return False, "identity or freshness uncertain"
    if not observation["purchasable"]:
        return False, "positive purchasability evidence missing"
    if observation["price_cents"] is None or observation["currency"] != "USD":
        return False, "price or currency uncertain"
    if not demo_rule:
        return False, "current MSRP/target rule unverified"
    if observation["price_cents"] > 10000:
        return False, "above synthetic demo target"
    return True, "synthetic USD 100.00 fixture rule satisfied"


def registry() -> dict:
    return {"products": [asdict(PRODUCT)], "sources": [asdict(SOURCE)]}
