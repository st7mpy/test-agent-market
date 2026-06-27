"""Market-making strategy (clean-room) — Avellaneda-Stoikov adapted to binary
prediction markets.

Quote symmetrically around an inventory-adjusted *reservation price*:

    reservation r = s - q * gamma * sigma^2 * tau
    half-spread   = 0.5 * ( gamma * sigma^2 * tau + (2/gamma) * ln(1 + gamma/k) )
    bid = r - half_spread,  ask = r + half_spread

where s = fair value (we use the microprice), q = signed inventory,
gamma = risk aversion, sigma = volatility, k = order-arrival intensity,
tau = time to resolution.

Prediction-market adaptations:
  * prices are clamped to [TICK, 1 - TICK];
  * sigma is a capped EWMA of recent returns (a Gaussian RW overstates tails near 0/1);
  * tau is floored and gamma is *ramped up* near resolution, because inventory
    does not de-risk smoothly — it jumps to $1 or $0 at the event time;
  * a min-spread floor covers fees/adverse selection;
  * at the inventory cap we quote one-sided; on a vol spike we widen or pull.

Technique references (read-only, not copied): Avellaneda & Stoikov (2008);
Hummingbot's A-S strategy (Apache-2.0) for parameter intuition; arXiv:2510.15205
on MM for bounded binary-outcome markets. Original implementation.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional

from .base import Context, Fill, Strategy
from .types import (
    BinaryMarket,
    Intent,
    LimitOrder,
    Side,
    TICK,
    TIF,
    Token,
    CancelAll,
)


@dataclass
class MMParams:
    market_id: str = ""
    gamma: float = 0.3               # risk aversion
    k: float = 100.0                 # order-arrival intensity (price^-1 scale for [0,1] books)
    quote_size: float = 200.0        # shares per side
    max_inventory: float = 1000.0    # |q| cap (sized to survive a 0/1 jump)
    min_spread: float = 0.01         # floor (covers fees + adverse selection)
    max_half_spread: float = 0.05    # cap; keeps quotes sane on a [0,1] market
    vol_window: int = 60             # ticks for EWMA vol
    vol_cap: float = 0.20            # cap on sigma
    vol_spike_mult: float = 3.0      # widen/pull if sigma > spike_mult * baseline
    tau_floor: float = 5.0           # periods; never let tau collapse the quote
    resolution_ramp: float = 4.0     # max gamma multiplier as tau -> tau_floor


class MarketMakerStrategy(Strategy):
    name = "market_maker"

    def __init__(self, params: MMParams) -> None:
        self.p = params
        self.q: float = 0.0                       # signed YES inventory
        self._prices: Deque[float] = deque(maxlen=params.vol_window)
        self._ewma_var: float = 0.0
        self._baseline_sigma: Optional[float] = None

    # ------------------------------------------------------------------ #
    def on_fill(self, fill: Fill) -> None:
        if fill.market_id != self.p.market_id or fill.token != Token.YES:
            return
        self.q += fill.size if fill.side == Side.BUY else -fill.size

    def _update_vol(self, mid: float) -> float:
        if self._prices:
            prev = self._prices[-1]
            if prev > 0:
                ret = (mid - prev) / prev
                lam = 2.0 / (self.p.vol_window + 1)
                self._ewma_var = (1 - lam) * self._ewma_var + lam * ret * ret
        self._prices.append(mid)
        sigma = min(math.sqrt(self._ewma_var), self.p.vol_cap)
        if self._baseline_sigma is None and len(self._prices) >= self.p.vol_window // 2:
            self._baseline_sigma = max(sigma, 1e-4)
        return sigma

    # ------------------------------------------------------------------ #
    def on_tick(self, ctx: Context) -> List[Intent]:
        m = ctx.markets.get(self.p.market_id)
        if m is None:
            return []
        s = m.yes_book.microprice()
        if s is None:
            return []
        sigma = self._update_vol(s)

        tau = max(m.time_to_resolution, self.p.tau_floor)
        # ramp gamma up as we approach resolution (forces flatter inventory)
        ramp = 1.0 + (self.p.resolution_ramp - 1.0) * (self.p.tau_floor / tau)
        gamma = self.p.gamma * ramp

        # vol-spike guard: pull quotes entirely on a sharp vol jump
        if (self._baseline_sigma is not None
                and sigma > self.p.vol_spike_mult * self._baseline_sigma):
            return [CancelAll("vol spike: pull quotes", self.p.market_id)]

        var = sigma * sigma
        # Inventory is normalised to [-1, 1] before skewing the reservation price,
        # otherwise share counts in the hundreds saturate a [0,1] price range.
        q_norm = max(-1.0, min(1.0, self.q / self.p.max_inventory))
        reservation = s - q_norm * gamma * var * tau
        half = 0.5 * (gamma * var * tau + (2.0 / gamma) * math.log(1.0 + gamma / self.p.k))
        half = min(max(half, self.p.min_spread / 2.0), self.p.max_half_spread)

        bid = _clamp(reservation - half)
        ask = _clamp(reservation + half)

        out: List[Intent] = []
        note = (f"AS r={reservation:.3f} half={half:.3f} q={self.q:.0f} "
                f"sigma={sigma:.4f} gamma={gamma:.2f}")
        # one-sided quoting at the inventory cap
        if self.q < self.p.max_inventory:
            out.append(LimitOrder(note, self.p.market_id, Token.YES, Side.BUY,
                                  bid, self.p.quote_size, TIF.GTC))
        if self.q > -self.p.max_inventory:
            out.append(LimitOrder(note, self.p.market_id, Token.YES, Side.SELL,
                                  ask, self.p.quote_size, TIF.GTC))
        return out


def _clamp(price: float) -> float:
    return max(TICK, min(1.0 - TICK, price))
