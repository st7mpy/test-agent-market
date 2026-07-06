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
"""
from __future__ import annotations

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


class DeltaNeutralYieldStrategy(Strategy):
    name = "delta_neutral_yield"

    def __init__(self, bankroll: float, params: DeltaNeutralParams | None = None) -> None:
        self.bankroll = bankroll
        self.p = params or DeltaNeutralParams()

    def on_tick(self, ctx: Context) -> List[Intent]:
        m = ctx.markets.get(self.p.market_id) or next(iter(ctx.markets.values()), None)
        if m is None:
            return []
        out: List[Intent] = []
        pos = ctx.portfolio.position(m.market_id)

        # 1) realize any matched sets: X YES + X NO -> $X (the harvested spread)
        matched = min(pos.yes, pos.no)
        if matched >= self.p.merge_min:
            out.append(Merge(f"dn merge {matched:.0f} sets -> ${matched:.0f}",
                             m.market_id, shares=matched))

        mid = m.yes_book.mid()
        if mid is None or not (self.p.min_mid <= mid <= self.p.max_mid):
            out.append(CancelAll("dn out-of-range: pull quotes", m.market_id))
            return out

        # 2) gross cap on carried legs (post-merge inventory)
        legs_value = (pos.yes - matched) * mid + (pos.no - matched) * (1.0 - mid)
        if legs_value >= self.p.gross_cap * self.bankroll:
            out.append(CancelAll("dn gross cap: pull quotes", m.market_id))
            return out

        # 3) two-sided passive bids summing to 1 − 2δ; gate the heavy side
        imbalance = pos.yes - pos.no
        yes_px = max(0.01, mid - self.p.half_spread)
        no_px = max(0.01, (1.0 - mid) - self.p.half_spread)
        note = (f"dn quote YES@{yes_px:.3f}+NO@{no_px:.3f} "
                f"(sum {yes_px + no_px:.3f}, imb {imbalance:+.0f})")
        if imbalance <= self.p.delta_band:
            out.append(LimitOrder(note, m.market_id, Token.YES, Side.BUY,
                                  yes_px, self.p.quote_size, TIF.GTC))
        if -imbalance <= self.p.delta_band:
            out.append(LimitOrder(note, m.market_id, Token.NO, Side.BUY,
                                  no_px, self.p.quote_size, TIF.GTC))
        return out
