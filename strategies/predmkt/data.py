"""Historical price data: live Polymarket public API + an offline fixture.

Polymarket exposes public, unauthenticated endpoints:
  * Gamma (market metadata): https://gamma-api.polymarket.com/markets
  * CLOB price history:      https://clob.polymarket.com/prices-history
    ?market=<clob_token_id>&interval=<max|1d|...>&fidelity=<minutes>

`fetch_polymarket_history` and `discover_token` use only the standard library
(urllib), honour HTTPS_PROXY, and trust the CA bundle in SSL_CERT_FILE /
REQUESTS_CA_BUNDLE if set — so they work in a normal networked environment.

NOTE: in some sandboxed sessions outbound access to polymarket.com is blocked by
egress policy; in that case use the bundled fixture (``load_fixture``), which is
stored in the exact CLOB ``prices-history`` shape so the calling code is
identical. The fixture is synthetic-but-schema-accurate (an election-style
market that resolves YES) because real data could not be fetched at authoring
time; replace it with a real series via ``--live`` when network is available.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.parse
import urllib.request
from typing import List, Optional, Tuple

GAMMA = "https://gamma-api.polymarket.com/markets"
CLOB_HISTORY = "https://clob.polymarket.com/prices-history"
DEFAULT_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "data", "sample_history.json")

PricePoint = Tuple[int, float]   # (unix_seconds, price)


# --------------------------------------------------------------------------- #
def _opener() -> urllib.request.OpenerDirector:
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    ctx = ssl.create_default_context(cafile=ca) if ca and os.path.exists(ca) else ssl.create_default_context()
    handlers: list = [urllib.request.HTTPSHandler(context=ctx)]
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"https": proxy, "http": proxy}))
    return urllib.request.build_opener(*handlers)


def _get_json(url: str, timeout: float = 30.0):
    req = urllib.request.Request(url, headers={"User-Agent": "predmkt-backtest/0.1"})
    with _opener().open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# --------------------------------------------------------------------------- #
def discover_token(query: str, *, closed: bool = True, limit: int = 50) -> Optional[dict]:
    """Find a resolved market whose question matches `query`; return its YES token.

    Returns {"question", "yes_token_id", "no_token_id", "outcome"} or None.
    """
    params = {"closed": str(closed).lower(), "limit": str(limit),
              "order": "volumeNum", "ascending": "false"}
    markets = _get_json(f"{GAMMA}?{urllib.parse.urlencode(params)}")
    q = query.lower()
    for m in markets:
        if q not in (m.get("question", "").lower()):
            continue
        token_ids = m.get("clobTokenIds")
        if isinstance(token_ids, str):
            token_ids = json.loads(token_ids)
        if not token_ids or len(token_ids) < 2:
            continue
        # winning outcome, if resolved
        outcome = None
        prices = m.get("outcomePrices")
        if isinstance(prices, str):
            prices = json.loads(prices)
        if prices and len(prices) >= 2:
            outcome = "YES" if float(prices[0]) > float(prices[1]) else "NO"
        return {"question": m.get("question"), "yes_token_id": token_ids[0],
                "no_token_id": token_ids[1], "outcome": outcome}
    return None


def fetch_polymarket_history(token_id: str, *, interval: str = "max",
                             fidelity: int = 60) -> List[PricePoint]:
    """Fetch a token's historical price series from the public CLOB endpoint."""
    params = {"market": token_id, "interval": interval, "fidelity": str(fidelity)}
    data = _get_json(f"{CLOB_HISTORY}?{urllib.parse.urlencode(params)}")
    return [(int(pt["t"]), float(pt["p"])) for pt in data.get("history", [])]


# --------------------------------------------------------------------------- #
def load_fixture(path: str = DEFAULT_FIXTURE) -> List[PricePoint]:
    with open(os.path.abspath(path)) as f:
        data = json.load(f)
    return [(int(pt["t"]), float(pt["p"])) for pt in data["history"]]
