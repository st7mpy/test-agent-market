"""Resolution-convergence "theta" strategy (clean-room).

Near-certain favorites rarely trade at exactly $1 before resolution: capital
locked in a 97c share earns nothing while it waits, so the last cents decay in
like option theta. Buying a 97c favorite three days from resolution risks 97c to
make 3c — terrible odds per trade, but as *carry* it can annualize well, and the
per-trade probability of loss is (by construction) small.

The whole strategy is therefore a short position on two risks, and it only makes
sense if both are priced:

  1. **The favorite is wrong** (true upsets). Handled by the hurdle: the
     annualized net return must beat `hurdle_apr`, so cheap time premium is
     never bought for its own sake, and by a per-trade risk budget sized so a
     full loss costs a bounded fraction of bankroll.
  2. **The favorite is "cheap for a reason"** — a pending dispute or ambiguous
     wording, i.e. oracle risk. That is exactly the repo's differentiator C:
     an `OracleRiskModel` (ADR-014) gates entry hard (`max_oracle_risk`,
     stricter by default than the platform-wide cap), because a UMA-style
     mis-resolution is the tail this strategy sells.

Timing controls: only act inside `max_ttr` periods of resolution (the carry zone),
and a stability guard skips any favorite that has slipped more than
`stability_veto` off its recent high — a 97c share that was 99c yesterday is not
decaying, it's repricing on news.

`time_to_resolution` is in model periods (the SDK's tick unit); `periods_per_year`
converts the per-trade return to an APR — set it to match the tick cadence
(e.g. 365 for daily replay data, 31_536_000/poll_seconds for live polling).

Technique references (read-only, not copied): standard carry/convergence framing;
Polymarket community writing on "sniping" near-resolution favorites. Original
implementation.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional

from .base import Context, Strategy, depth_capped_size
from .fees import taker_fee_per_share
from .oracle_risk import OracleRiskModel
from .types import BinaryMarket, Intent, LimitOrder, Side, TIF, Token


@dataclass
class ThetaParams:
    min_price: float = 0.85          # only favorites at/above this are carry candidates
    max_ttr: float = 30.0            # act only within this many periods of resolution
    hurdle_apr: float = 0.30         # required annualized net return
    periods_per_year: float = 365.0  # tick-unit -> year conversion (match your data cadence)
    risk_per_market: float = 0.02    # max bankroll fraction lost if the favorite loses
    gross_cap: float = 0.50          # max bankroll fraction deployed by this strategy
    depth_fraction: float = 0.25     # cap size to 25% of fillable depth
    stability_window: int = 30       # ticks of history for the repricing guard
    stability_veto: float = 0.03     # skip if price slipped this far off its recent high
    max_oracle_risk: float = 0.25    # strict: mis-resolution is the tail being sold


class ThetaConvergenceStrategy(Strategy):
    name = "theta_convergence"

    def __init__(self, bankroll: float, params: ThetaParams | None = None,
                 oracle_model: Optional[OracleRiskModel] = None) -> None:
        self.bankroll = bankroll
        self.p = params or ThetaParams()
        self.oracle_model = oracle_model
        self._hist: Dict[str, Deque[float]] = {}

    # ------------------------------------------------------------------ #
    @staticmethod
    def annualized_return(ask: float, fee: float, ttr: float,
                          periods_per_year: float) -> float:
        """Net APR of buying the favorite at `ask` and holding to a $1 payout."""
        cost = ask + fee
        if cost <= 0 or cost >= 1.0 or ttr <= 0:
            return 0.0
        per_trade = (1.0 - cost) / cost
        years = ttr / periods_per_year
        return (1.0 + per_trade) ** (1.0 / years) - 1.0

    def _record(self, market_id: str, price: float) -> None:
        self._hist.setdefault(market_id, deque(maxlen=self.p.stability_window)).append(price)

    def _repricing(self, market_id: str, price: float) -> bool:
        """True if the favorite slipped off its recent high — news, not decay."""
        h = self._hist.get(market_id)
        if not h:
            return False
        return (max(h) - price) > self.p.stability_veto

    def _gross_deployed(self, ctx: Context) -> float:
        total = 0.0
        for mid_id, pos in ctx.portfolio.positions.items():
            mk = ctx.markets.get(mid_id)
            px = mk.yes_book.mid() if mk and mk.yes_book.mid() is not None else 0.5
            total += pos.yes * px + pos.no * (1.0 - px)
        return total

    # ------------------------------------------------------------------ #
    def on_tick(self, ctx: Context) -> List[Intent]:
        out: List[Intent] = []
        for m in ctx.markets.values():
            intent = self._consider(m, ctx)
            if intent is not None:
                out.append(intent)
        return out

    def _consider(self, m: BinaryMarket, ctx: Context) -> Optional[LimitOrder]:
        mid = m.yes_book.mid()
        if mid is None:
            return None
        # favorite side and its executable price
        favorite = Token.YES if mid >= 0.5 else Token.NO
        ask = m.book(favorite).best_ask()
        fav_mid = mid if favorite == Token.YES else 1.0 - mid
        self._record(m.market_id, fav_mid)
        if ask is None or ask < self.p.min_price or ask >= 1.0:
            return None
        if m.time_to_resolution > self.p.max_ttr:
            return None                          # not in the carry zone yet
        if self.oracle_model is not None and self.oracle_model.score(m) > self.p.max_oracle_risk:
            return None                          # cheap for a reason — dispute risk
        if self._repricing(m.market_id, fav_mid):
            return None                          # slipping favorite = news, skip

        fee = taker_fee_per_share(m.venue, ask, m.category)
        apr = self.annualized_return(ask, fee, m.time_to_resolution, self.p.periods_per_year)
        if apr < self.p.hurdle_apr:
            return None

        # one bite per market
        pos = ctx.portfolio.position(m.market_id)
        held = pos.yes if favorite == Token.YES else pos.no
        if held > 0:
            return None

        # sizing: full loss (favorite -> 0) costs at most risk_per_market of bankroll
        budget = self.p.risk_per_market * self.bankroll
        room = max(0.0, self.p.gross_cap * self.bankroll - self._gross_deployed(ctx))
        notional = min(budget, room)
        if notional <= 0:
            return None
        shares = notional / ask
        shares = min(shares, depth_capped_size(m.book(favorite), Side.BUY, ask,
                                               self.p.depth_fraction, shares))
        if shares <= 0:
            return None
        return LimitOrder(
            f"theta fav={favorite.value} ask={ask:.3f} ttr={m.time_to_resolution:.0f} "
            f"apr={apr:.1%}",
            m.market_id, favorite, Side.BUY, ask, shares, TIF.IOC)
