"""Delta-neutral set-minting yield strategy (strategy 8) — "park funds" mode.

The one structural free lunch in a binary CTF market: a **complete set**
(1 YES + 1 NO) redeems exactly $1 whatever happens — even under a *wrong*
resolution, the two legs still sum to $1. So inventory held as matched sets has
zero delta and (uniquely among our strategies) near-zero oracle exposure, which
is why this strategy is exempt from the ADR-014 entry gate: the only directional
risk it ever carries is the *unmatched* leg, and that is capped by `delta_band`.

The loop:
  1. Rest passive bids on BOTH books: BUY YES at ``mid − δ`` and BUY NO at
     ``(1 − mid) − δ``, so the two prices always sum to ``1 − 2δ``.
  2. When both legs fill, ``Merge`` the matched amount: X YES + X NO → $X. Each
     merged set realizes the 2δ discount as riskless cash.
  3. If one side runs ahead (|YES − NO| > ``delta_band``), stop quoting the heavy
     side until the book fills the lagging leg — exposure stays bracketed.

On the real venue this stacks three income streams (differentiator B): the 2δ
minting spread simulated here, plus **maker rebates** (a % of taker fees) and
**liquidity rewards** for resting near the mid — both venue-paid and therefore
NOT simulated by the paper broker; track them with ``phase0_journal.py income``
when trading for real. Fills here are the paper broker's optimistic
mid-touch fills, so treat replay PnL as an upper bound on the spread leg.

This is the "delta-neutral yield bot": run it via the runner
(``python run.py --config ../deploy/config.deltaneutral.json``) against replay or
live *data*; real order placement stays platform-side by design (ADR-002).

CAVEATS measured on real Polymarket crypto data (2026-07-04 backtests):
  * **Universe scarcity.** Most crypto price markets sit at extremes (a $250k-BTC
    longshot with 1,005 history points ranged 0.013-0.015 — 0% inside the
    tradeable band). The bot correctly idles there; returns depend on *market
    selection*: pick mids in ~0.15-0.85 with a tight book and an active
    liquidity-reward program, and prefer running several markets in parallel.
  * **Calm-market fill starvation.** Live mid-range crypto books barely move at
    short horizons (90 samples over 3 min on two markets: zero mid changes), so
    quotes δ away are rarely reached BY PRICE. `requote_threshold` (anchoring)
    lets slow drifts reach a standing quote; `auto_spread` adapts δ to measured
    vol. On the real venue, calm-market income is mostly the venue-paid layer.
  * **Paper fill model is directional.** It fills only when the MID moves to the
    quote — real maker fills come from taker flow hitting a resting order while
    the mid stands still. Paper therefore UNDERSTATES calm-market income (no
    taker flow, no rebates/rewards) and OVERSTATES volatile-market income (no
    queue position, no adverse selection). Read `stats["two_sided"]/["ticks"]`
    (quote-uptime) as the liquidity-reward accrual proxy.
  * **Trend bleed is the loss mode.** A monotone repricing fills only the
    fading side up to `delta_band`; that leg settles against you. Expected worst
    case ≈ band × entry price (fixture: −0.33% on a trending market with
    band 300). Size `delta_band` as an explicit loss budget.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import List

from .base import Context, Strategy
from .types import BinaryMarket, CancelAll, Intent, LimitOrder, Merge, Side, TIF, Token


@dataclass
class DeltaNeutralParams:
    market_id: str = ""
    quote_size: float = 200.0        # shares per leg per requote
    half_spread: float = 0.01        # δ: per-leg discount; a merged set nets ~2δ
    delta_band: float = 300.0        # max |YES − NO| before one-sided quoting
    gross_cap: float = 0.50          # max fraction of bankroll held in legs
    min_mid: float = 0.10            # only run where both books are two-sided
    max_mid: float = 0.90
    merge_min: float = 1.0           # don't bother merging dust
    # anchor quotes instead of chasing the mid every tick: re-center only when
    # |mid - anchor| >= requote_threshold, so slow drifts can actually REACH the
    # quotes (backtests on real crypto series: chasing quotes never fill on drift).
    # 0.0 = legacy chase-every-tick behavior.
    requote_threshold: float = 0.0
    # vol-aware spread: δ_t = clamp(vol_mult · σ(recent mid changes),
    # half_spread, half_spread_max). Calm books quote tight (real income there is
    # venue-paid anyway); jumpy books quote wide. Off by default.
    auto_spread: bool = False
    vol_window: int = 60
    vol_mult: float = 3.0
    half_spread_max: float = 0.04


class DeltaNeutralYieldStrategy(Strategy):
    name = "delta_neutral_yield"

    def __init__(self, bankroll: float, params: DeltaNeutralParams | None = None) -> None:
        self.bankroll = bankroll
        self.p = params or DeltaNeutralParams()
        self._anchor: float | None = None
        self._mids: deque[float] = deque(maxlen=max(2, self.p.vol_window))
        # session diagnostics: quote-uptime is the proxy for the venue-paid
        # liquidity-reward accrual the paper broker cannot simulate.
        self.stats = {"ticks": 0, "in_range": 0, "two_sided": 0,
                      "merges": 0, "sets_merged": 0.0}

    def _half_spread(self) -> float:
        if not self.p.auto_spread or len(self._mids) < 2:
            return self.p.half_spread
        ds = [self._mids[i] - self._mids[i - 1] for i in range(1, len(self._mids))]
        sigma = (sum(d * d for d in ds) / len(ds)) ** 0.5
        return min(self.p.half_spread_max, max(self.p.half_spread, self.p.vol_mult * sigma))

    def on_tick(self, ctx: Context) -> List[Intent]:
        m = ctx.markets.get(self.p.market_id) or next(iter(ctx.markets.values()), None)
        if m is None:
            return []
        out: List[Intent] = []
        pos = ctx.portfolio.position(m.market_id)
        self.stats["ticks"] += 1

        # 1) realize any matched sets: X YES + X NO -> $X (the harvested spread)
        matched = min(pos.yes, pos.no)
        if matched >= self.p.merge_min:
            self.stats["merges"] += 1
            self.stats["sets_merged"] += matched
            out.append(Merge(f"dn merge {matched:.0f} sets -> ${matched:.0f}",
                             m.market_id, shares=matched))

        mid = m.yes_book.mid()
        if mid is None or not (self.p.min_mid <= mid <= self.p.max_mid):
            self._anchor = None
            out.append(CancelAll("dn out-of-range: pull quotes", m.market_id))
            return out
        self.stats["in_range"] += 1
        self._mids.append(mid)

        # 2) gross cap on carried legs (post-merge inventory)
        legs_value = (pos.yes - matched) * mid + (pos.no - matched) * (1.0 - mid)
        if legs_value >= self.p.gross_cap * self.bankroll:
            self._anchor = None
            out.append(CancelAll("dn gross cap: pull quotes", m.market_id))
            return out

        # 3) anchor: re-center quotes only when the mid has moved enough — a
        # standing quote is what a drifting mid fills into (and what the venue's
        # liquidity-reward program pays for resting).
        if self._anchor is None or abs(mid - self._anchor) >= self.p.requote_threshold:
            self._anchor = mid
        anchor = self._anchor

        # 4) two-sided passive bids summing to 1 − 2δ; gate the heavy side
        delta = self._half_spread()
        imbalance = pos.yes - pos.no
        yes_px = max(0.01, anchor - delta)
        no_px = max(0.01, (1.0 - anchor) - delta)
        note = (f"dn quote YES@{yes_px:.3f}+NO@{no_px:.3f} "
                f"(sum {yes_px + no_px:.3f}, d={delta:.3f}, imb {imbalance:+.0f})")
        quoted = 0
        if imbalance <= self.p.delta_band:
            quoted += 1
            out.append(LimitOrder(note, m.market_id, Token.YES, Side.BUY,
                                  yes_px, self.p.quote_size, TIF.GTC))
        if -imbalance <= self.p.delta_band:
            quoted += 1
            out.append(LimitOrder(note, m.market_id, Token.NO, Side.BUY,
                                  no_px, self.p.quote_size, TIF.GTC))
        if quoted == 2:
            self.stats["two_sided"] += 1
        return out
