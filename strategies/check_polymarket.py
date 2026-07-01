#!/usr/bin/env python3
"""Polymarket public-API reachability check.

    cd strategies
    python check_polymarket.py

Exercises the real gamma + CLOB endpoints (via predmkt/data.py, with browser-like
headers) and reports OK/BLOCKED per endpoint. A 403/451 almost always means a
Cloudflare or **geographic IP block** (e.g. running from India, or a flagged
datacenter IP) — NOT a code bug. Fix: run from a supported-region VM (US/EU); see
DEPLOY_DATA.md. Exit code 0 if reachable, 1 if fully blocked (handy on a VM / CI).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse

from predmkt import data


def _try(label, fn):
    t0 = time.time()
    try:
        out = fn()
        print(f"  [ OK ]   {label}   ({(time.time() - t0) * 1000:.0f} ms)")
        return True, out
    except Exception as e:  # noqa: BLE001 - report any failure mode uniformly
        first = str(e).splitlines()[0] if str(e) else ""
        print(f"  [BLOCK]  {label}   ({(time.time() - t0) * 1000:.0f} ms)")
        print(f"           {type(e).__name__}: {first[:220]}")
        return False, None


def _get_markets(limit: int):
    params = {"closed": "false", "limit": str(limit), "order": "volumeNum", "ascending": "false"}
    return data._get_json(f"{data.GAMMA}?{urllib.parse.urlencode(params)}")


def _first_token(markets):
    for m in markets or []:
        tids = m.get("clobTokenIds")
        if isinstance(tids, str):
            tids = json.loads(tids)
        if tids and len(tids) >= 2:
            return m.get("question", "?"), tids[0]
    return None, None


def main() -> None:
    ap = argparse.ArgumentParser(description="Check Polymarket public API reachability")
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    print("=" * 68)
    print("  POLYMARKET API REACHABILITY CHECK")
    print(f"  user-agent : {'custom ($PREDMKT_USER_AGENT)' if os.environ.get('PREDMKT_USER_AGENT') else 'default browser UA'}")
    print(f"  https proxy: {proxy or 'none'}")
    print("=" * 68)

    results = []

    ok_gamma, markets = _try("Gamma   GET /markets (metadata)", lambda: _get_markets(args.limit))
    results.append(ok_gamma)

    question, token = (None, None)
    if ok_gamma:
        question, token = _first_token(markets)
        print(f"           -> {len(markets)} markets; sample: {str(question)[:56]!r}")

    if token:
        ok_book, _ = _try("CLOB    GET /book (live order book)",
                          lambda: data.fetch_polymarket_book(token))
        results.append(ok_book)
        ok_hist, hist = _try("CLOB    GET /prices-history",
                             lambda: data.fetch_polymarket_history(token, interval="1d", fidelity=60))
        results.append(ok_hist)
        if ok_hist and hist:
            print(f"           -> {len(hist)} price points; last p={hist[-1][1]:.3f}")
    else:
        print("  [skip]   CLOB book/history — no token id (Gamma unreachable or no market)")

    print("=" * 68)
    if results and all(results):
        print("  RESULT: REACHABLE — live Polymarket data works from this network.")
        print("          Run:  python backtest.py --strategy mm --live --query \"election\"")
        code = 0
    elif any(results):
        print("  RESULT: PARTIAL — some endpoints reachable (see BLOCK lines above).")
        code = 0
    else:
        print("  RESULT: BLOCKED — no Polymarket endpoint reachable from this network.")
        print("          403/451 = Cloudflare or geographic IP block (e.g. India / datacenter),")
        print("          not a code bug. Run from a supported-region VM (US/EU) — see DEPLOY_DATA.md.")
        print("          Offline still works:  python backtest.py --strategy mm")
        code = 1
    print("=" * 68)
    sys.exit(code)


if __name__ == "__main__":
    main()
