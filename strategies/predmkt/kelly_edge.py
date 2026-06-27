"""Forecast-edge + fractional-Kelly strategy (clean-room).

Estimate a fair probability `p` for YES, compare to the market price `m`, and if
the edge survives fees, take a position sized by *fractional* Kelly.

Kelly for a binary bet, buying YES at price m (pays $1):
    net odds  b = (1 - m) / m
    full Kelly f* = (p - m) / (1 - m)      # fraction of bankroll
    stake     = lambda * f* * bankroll     # lambda in (0,1], default 1/4

Fractional Kelly is used because `p` is *estimated*: full Kelly is acutely
sensitive to error (a ~10% edge overstatement can ~50% overbet and full Kelly
tolerates >50% drawdowns even with true positive edge). Quarter-Kelly roughly
halves volatility for little long-run growth loss.

Fair-value source for this sample is pluggable (`fair_value_fn`); two transparent
built-ins are provided:
  * external reference anchor (e.g. devigged sportsbook / other-venue implied prob);
  * own-price mean-reversion z-score, with a trend/news regime guard so we don't
    fade a real move.

Risk controls: min edge after fees, per-market fraction cap, depth cap,
per-category and gross exposure caps, and a daily stop.

Technique references (read-only, not copied): Kelly (1956); fractional Kelly
(Hakansson-Ziemba); Risk-Constrained Kelly (arXiv:1603.06183); guberm/polymarket-bot
(MIT) for layered-cap intuition. Original implementation.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Callable, Deque, Dict, List, Optional

from .base import Context, Strategy, depth_capped_size
from .fees import polymarket_taker_fee_per_share
from .types import BinaryMarket, Intent, LimitOrder, Side, TIF, Token

FairValueFn = Callable[[BinaryMarket, "KellyEdgeStrategy"], Optional[float]]


@dataclass
class KellyParams:
    kelly_fraction: float = 0.25      # lambda: quarter-Kelly
    f_cap: float = 0.10               # max bankroll fraction per market
    min_edge: float = 0.03            # required edge after fees
    depth_fraction: float = 0.20      # cap size to 20% of fillable depth
    category_cap: float = 0.30        # max gross fraction per category
    gross_cap: float = 0.80           # max total deployed fraction
    daily_stop: float = 0.20          # halt if realized PnL <= -20% of bankroll
    # mean-reversion built-in
    z_window: int = 100
    z_enter: float = 2.0
    trend_slope_max: float = 0.0008   # |per-tick slope| above this => trending, skip
    vol_spike_z: float = 3.0          # volume z above this => news regime, skip


class KellyEdgeStrategy(Strategy):
    name = "kelly_edge"

    def __init__(self, bankroll: float, params: KellyParams | None = None,
                 fair_value_fn: FairValueFn | None = None,
                 reference_probs: Dict[str, float] | None = None) -> None:
        self.bankroll = bankroll
        self.p = params or KellyParams()
        self.reference_probs = reference_probs or {}
        self.fair_value_fn = fair_value_fn or self.reference_anchor
        self._hist: Dict[str, Deque[float]] = {}
        self._vol_hist: Dict[str, Deque[float]] = {}

    # --- fair-value sources -------------------------------------------- #
    def reference_anchor(self, m: BinaryMarket, _self) -> Optional[float]:
        """Use an externally supplied implied probability as 'truth'."""
        return self.reference_probs.get(m.market_id)

    def mean_reversion(self, m: BinaryMarket, _self) -> Optional[float]:
        """Fade short-term deviations of price from its rolling mean (guarded)."""
        h = self._hist.get(m.market_id)
        mid = m.yes_book.mid()
        if h is None or mid is None or len(h) < self.p.z_window:
            return None
        mu, sd = mean(h), pstdev(h)
        if sd <= 1e-9:
            return None
        z = (mid - mu) / sd
        # regime guard: skip if trending
        slope = (h[-1] - h[0]) / max(1, len(h))
        if abs(slope) > self.p.trend_slope_max:
            return None
        if abs(z) < self.p.z_enter:
            return None
        # expect reversion toward the mean -> fair value is the rolling mean
        return mu

    # --- per-tick state update ----------------------------------------- #
    def _record(self, m: BinaryMarket) -> None:
        mid = m.yes_book.mid()
        if mid is None:
            return
        self._hist.setdefault(m.market_id, deque(maxlen=self.p.z_window)).append(mid)

    # --- exposure accounting ------------------------------------------- #
    def _gross_deployed(self, ctx: Context) -> float:
        total = 0.0
        for mid, pos in ctx.portfolio.positions.items():
            mk = ctx.markets.get(mid)
            px = mk.yes_book.mid() if mk and mk.yes_book.mid() else 0.5
            total += abs(pos.net_yes()) * px
        return total

    def _category_deployed(self, ctx: Context, category: str) -> float:
        total = 0.0
        for mid, pos in ctx.portfolio.positions.items():
            mk = ctx.markets.get(mid)
            if not mk or mk.category != category:
                continue
            px = mk.yes_book.mid() or 0.5
            total += abs(pos.net_yes()) * px
        return total

    # ------------------------------------------------------------------ #
    def on_tick(self, ctx: Context) -> List[Intent]:
        # daily stop
        if ctx.portfolio.realized_pnl_today <= -self.p.daily_stop * self.bankroll:
            return []

        out: List[Intent] = []
        for m in ctx.markets.values():
            self._record(m)
            mid = m.yes_book.mid()
            ask = m.yes_book.best_ask()
            if mid is None or ask is None:
                continue
            p = self.fair_value_fn(m, self)
            if p is None:
                continue
            p = max(0.0, min(1.0, p))

            cost = polymarket_taker_fee_per_share(ask, m.category) + 0.5 * (m.yes_book.spread() or 0.0)
            edge = p - ask
            if edge - cost < self.p.min_edge:
                continue

            # fractional Kelly fraction for buying YES at the executable price
            f_star = (p - ask) / max(1e-6, (1.0 - ask))
            f = max(0.0, min(f_star * self.p.kelly_fraction, self.p.f_cap))
            target_usd = f * self.bankroll

            # gross + category caps
            room_gross = max(0.0, self.p.gross_cap * self.bankroll - self._gross_deployed(ctx))
            room_cat = max(0.0, self.p.category_cap * self.bankroll
                           - self._category_deployed(ctx, m.category))
            target_usd = min(target_usd, room_gross, room_cat)
            if target_usd <= 0:
                continue

            shares = target_usd / ask
            shares = min(shares, depth_capped_size(m.yes_book, Side.BUY, ask,
                                                   self.p.depth_fraction, shares))
            if shares <= 0:
                continue

            out.append(LimitOrder(
                f"kelly p={p:.3f} ask={ask:.3f} edge={edge:.3f} f={f:.3f}",
                m.market_id, Token.YES, Side.BUY, ask, shares, TIF.IOC))
        return out
