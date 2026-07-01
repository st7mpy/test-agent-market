"""Historical price data: live Polymarket public API + an offline fixture.

Polymarket exposes public, unauthenticated endpoints:
  * Gamma (market metadata): https://gamma-api.polymarket.com/markets
  * CLOB price history:      https://clob.polymarket.com/prices-history
    ?market=<clob_token_id>&interval=<max|1d|...>&fidelity=<minutes>

`fetch_polymarket_history` and `discover_token` use only the standard library
(urllib), send **browser-like headers** (UA + Origin/Referer, override via
``$PREDMKT_USER_AGENT``), honour ``HTTPS_PROXY``, and trust the CA bundle in
``SSL_CERT_FILE`` / ``REQUESTS_CA_BUNDLE`` if set — so they work in a normal
networked environment. Run ``python check_polymarket.py`` to test reachability.

NOTE: access can fail two ways. (1) A **Cloudflare bare-client 403** — fixed by the
browser-like headers above. (2) A **geographic/IP block** (a geofenced region such
as India, or a flagged datacenter IP) — headers won't help; run from a supported
region (US/EU VM) per ``strategies/DEPLOY_DATA.md``. In either case (or offline) use
the bundled fixture (``load_fixture``), stored in the exact CLOB ``prices-history``
shape so the calling code is identical — replace it with a real series via ``--live``
once reachable.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional, Tuple

from .types import OrderBook

GAMMA = "https://gamma-api.polymarket.com/markets"
CLOB_HISTORY = "https://clob.polymarket.com/prices-history"
CLOB_BOOK = "https://clob.polymarket.com/book"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
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


# A browser-like UA + Origin/Referer clears Cloudflare's bare-client 403 in most
# cases. A *geographic* block (e.g. India / flagged datacenter IPs) is different —
# it needs a request from a supported region (see strategies/DEPLOY_DATA.md).
# Override the UA with $PREDMKT_USER_AGENT if a venue rotates its bot rules.
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _headers() -> dict:
    return {
        "User-Agent": os.environ.get("PREDMKT_USER_AGENT", _DEFAULT_UA),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://polymarket.com",
        "Referer": "https://polymarket.com/",
    }


def _get_json(url: str, timeout: float = 30.0):
    req = urllib.request.Request(url, headers=_headers())
    try:
        with _opener().open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (403, 451):
            endpoint = url.split("?")[0]
            raise RuntimeError(
                f"HTTP {e.code} from {endpoint} — almost always a Cloudflare/geo IP block "
                f"(a geofenced region like India, or a flagged datacenter IP), not a code bug. "
                f"Fix: run from a supported-region VM (US/EU), or set $PREDMKT_USER_AGENT / "
                f"$HTTPS_PROXY. See strategies/DEPLOY_DATA.md."
            ) from e
        raise


# --------------------------------------------------------------------------- #
def discover_token(query: str, *, closed: bool = True, limit: int = 50,
                   max_pages: int = 6) -> Optional[dict]:
    """Find a market whose question matches `query`; return its YES/NO tokens.

    Scans up to ``max_pages`` pages of ``limit`` markets ordered by volume (so a
    lower-volume market is still reachable — a single page of 50 misses most of
    the book). First substring match wins. Returns
    {"question", "yes_token_id", "no_token_id", "outcome"} or None.
    """
    q = query.lower()
    for page in range(max(1, max_pages)):
        params = {"closed": str(closed).lower(), "limit": str(limit),
                  "offset": str(page * limit), "order": "volumeNum", "ascending": "false"}
        markets = _get_json(f"{GAMMA}?{urllib.parse.urlencode(params)}")
        if not markets:
            break
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
        if len(markets) < limit:
            break   # last page
    return None


def fetch_polymarket_history(token_id: str, *, interval: str = "max",
                             fidelity: int = 60) -> List[PricePoint]:
    """Fetch a token's historical price series from the public CLOB endpoint."""
    params = {"market": token_id, "interval": interval, "fidelity": str(fidelity)}
    data = _get_json(f"{CLOB_HISTORY}?{urllib.parse.urlencode(params)}")
    return [(int(pt["t"]), float(pt["p"])) for pt in data.get("history", [])]


def fetch_polymarket_book(token_id: str) -> OrderBook:
    """Fetch a token's live L2 order book from the public CLOB endpoint."""
    data = _get_json(f"{CLOB_BOOK}?token_id={urllib.parse.quote(str(token_id))}")
    bids = sorted(((float(l["price"]), float(l["size"])) for l in data.get("bids", [])),
                  key=lambda x: -x[0])
    asks = sorted(((float(l["price"]), float(l["size"])) for l in data.get("asks", [])),
                  key=lambda x: x[0])
    return OrderBook(bids=bids, asks=asks)


def fetch_kalshi_books(ticker: str) -> Tuple[OrderBook, OrderBook]:
    """Fetch a Kalshi market's books and convert to (yes_book, no_book) in [0,1].

    Kalshi's public orderbook returns resting *bids* only, in cents (1-99):
    ``{"orderbook": {"yes": [[price, size], ...], "no": [[price, size], ...]}}``.
    A resting NO bid at q implies a YES *ask* at (1 - q), and vice-versa — so each
    side's asks are the mirror of the other side's bids. Untested in-session
    (network); the conversion is the part worth getting right.
    """
    data = _get_json(f"{KALSHI}/markets/{urllib.parse.quote(str(ticker))}/orderbook")
    ob = data.get("orderbook", {}) or {}
    yes = ob.get("yes") or []   # resting YES bids (price cents, size)
    no = ob.get("no") or []     # resting NO bids
    yes_bids = sorted(((p / 100.0, float(s)) for p, s in yes), key=lambda x: -x[0])
    no_bids = sorted(((p / 100.0, float(s)) for p, s in no), key=lambda x: -x[0])
    yes_asks = sorted(((1.0 - p / 100.0, float(s)) for p, s in no), key=lambda x: x[0])
    no_asks = sorted(((1.0 - p / 100.0, float(s)) for p, s in yes), key=lambda x: x[0])
    return OrderBook(bids=yes_bids, asks=yes_asks), OrderBook(bids=no_bids, asks=no_asks)


# --------------------------------------------------------------------------- #
def load_fixture(path: str = DEFAULT_FIXTURE) -> List[PricePoint]:
    with open(os.path.abspath(path)) as f:
        data = json.load(f)
    return [(int(pt["t"]), float(pt["p"])) for pt in data["history"]]
