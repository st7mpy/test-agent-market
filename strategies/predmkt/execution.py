"""Paper execution layer (ARCHITECTURE.md C4 + C5).

Models the trusted side of the intent boundary as three components, so this
skeleton can later swap the paper broker for the real KMS-backed Execution/OMS
without touching strategies:

  * `RiskGate`  — validates every intent (limits, mandate, depth, kill-switch).
  * `PaperBroker` — simulates fills against the live book; holds the paper book.
  * `PaperOMS`  — orchestrates: settle resting -> strategy.on_tick -> risk-check
    each intent -> execute approved -> mark to market.

The strategy never reaches the broker directly; everything passes the RiskGate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .base import Context, Fill
from .fees import polymarket_taker_fee
from .types import (
    BinaryMarket, CancelAll, Intent, LimitOrder, Merge, Portfolio, Side, Split,
    TIF, Token, Venue,
)


# --------------------------------------------------------------------------- #
@dataclass
class RiskLimits:
    max_position_shares: float = 5000.0
    max_order_notional: float = 10_000.0
    max_book_fraction: float = 0.5          # taker order <= this * visible depth
    allowed_categories: Optional[Sequence[str]] = None
    allowed_venues: Optional[Sequence[Venue]] = None


class RiskGate:
    """Single validated choke point. Returns (approved, reason)."""

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()
        self.kill_switch = False

    def check(self, it: Intent, pf: Portfolio, m: BinaryMarket) -> Tuple[bool, str]:
        if self.kill_switch:
            return False, "kill-switch engaged"
        L = self.limits
        if isinstance(it, CancelAll):
            return True, "ok"
        if isinstance(it, Merge):
            return True, "ok"                # only reduces exposure
        if isinstance(it, Split):
            if it.usdc > L.max_order_notional:
                return False, f"split notional {it.usdc:.0f} > cap"
            return True, "ok"
        if isinstance(it, LimitOrder):
            if L.allowed_categories is not None and m.category not in L.allowed_categories:
                return False, f"category {m.category} not in mandate"
            if L.allowed_venues is not None and m.venue not in L.allowed_venues:
                return False, f"venue {m.venue} not in mandate"
            if it.size * it.price > L.max_order_notional:
                return False, "order notional > cap"
            pos = pf.position(it.market_id)
            cur = pos.yes if it.token == Token.YES else pos.no
            proj = cur + (it.size if it.side == Side.BUY else -it.size)
            if abs(proj) > L.max_position_shares:
                return False, f"projected position {proj:.0f} > limit"
            if it.tif in (TIF.IOC, TIF.FOK):        # taker depth guard
                fillable = m.book(it.token).fillable_size(it.side, it.price)
                if it.size > L.max_book_fraction * fillable + 1e-9:
                    return False, "order exceeds depth-fraction guard"
            return True, "ok"
        return False, f"unknown intent {type(it).__name__}"


# --------------------------------------------------------------------------- #
@dataclass
class _Resting:
    market_id: str
    token: Token
    side: Side
    price: float
    size: float


class PaperBroker:
    def __init__(self, portfolio: Portfolio) -> None:
        self.pf = portfolio
        self.resting: List[_Resting] = []
        self._pending: List[_Resting] = []
        self.n_fills = 0
        self.fees_paid = 0.0

    # taker fills walk the book; maker quotes rest and fill when the mid crosses
    def execute(self, it: Intent, m: BinaryMarket) -> List[Fill]:
        if isinstance(it, Split):
            self.pf.cash -= it.usdc
            p = self.pf.position(it.market_id or m.market_id)
            p.yes += it.usdc
            p.no += it.usdc
            return []
        if isinstance(it, Merge):
            p = self.pf.position(it.market_id or m.market_id)
            p.yes -= it.shares
            p.no -= it.shares
            self.pf.cash += it.shares
            return []
        if isinstance(it, CancelAll):
            self.resting = [r for r in self.resting if r.market_id != (it.market_id or m.market_id)]
            self._pending = [r for r in self._pending if r.market_id != (it.market_id or m.market_id)]
            return []
        if isinstance(it, LimitOrder):
            if it.tif in (TIF.IOC, TIF.FOK):
                return self._take(it, m)
            self._pending.append(_Resting(it.market_id, it.token, it.side, it.price, it.size))
            return []
        return []

    def _take(self, it: LimitOrder, m: BinaryMarket) -> List[Fill]:
        book = m.book(it.token)
        levels = book.asks if it.side == Side.BUY else book.bids
        remaining, cost, filled = it.size, 0.0, 0.0
        for price, sz in levels:
            if it.side == Side.BUY and price > it.price + 1e-12:
                break
            if it.side == Side.SELL and price < it.price - 1e-12:
                break
            take = min(remaining, sz)
            cost += take * price
            filled += take
            remaining -= take
            if remaining <= 1e-12:
                break
        if filled <= 0:
            return []
        avg = cost / filled
        fee = polymarket_taker_fee(avg, filled, m.category)
        self.fees_paid += fee
        self.n_fills += 1
        p = self.pf.position(it.market_id or m.market_id)
        if it.side == Side.BUY:
            self.pf.cash -= cost + fee
            setattr(p, it.token.value.lower(), getattr(p, it.token.value.lower()) + filled)
        else:
            self.pf.cash += cost - fee
            setattr(p, it.token.value.lower(), getattr(p, it.token.value.lower()) - filled)
        return [Fill(it.market_id or m.market_id, it.token, it.side, avg, filled)]

    def settle_resting(self, m: BinaryMarket) -> List[Fill]:
        fills: List[Fill] = []
        keep: List[_Resting] = []
        for r in self.resting:
            mid = m.book(r.token).mid()
            if mid is None:
                keep.append(r)
                continue
            hit = (r.side == Side.BUY and mid <= r.price) or (r.side == Side.SELL and mid >= r.price)
            if not hit:
                keep.append(r)
                continue
            p = self.pf.position(r.market_id)
            if r.side == Side.BUY:                       # maker fee = 0 on Polymarket
                self.pf.cash -= r.size * r.price
                setattr(p, r.token.value.lower(), getattr(p, r.token.value.lower()) + r.size)
            else:
                self.pf.cash += r.size * r.price
                setattr(p, r.token.value.lower(), getattr(p, r.token.value.lower()) - r.size)
            self.n_fills += 1
            fills.append(Fill(r.market_id, r.token, r.side, r.price, r.size))
        self.resting = keep
        return fills

    def replace_resting(self) -> None:
        # fresh quotes cancel-replace any that were not (re)issued this tick
        ids = {r.market_id for r in self._pending}
        self.resting = [r for r in self.resting if r.market_id not in ids] + self._pending
        self._pending = []

    def mark_to_market(self, m: BinaryMarket) -> float:
        equity = self.pf.cash
        mid = m.yes_book.mid()
        for mid_id, pos in self.pf.positions.items():
            yp = mid if (mid_id == m.market_id and mid is not None) else 0.5
            equity += pos.yes * yp + pos.no * (1.0 - yp)
        return equity

    def settle(self, m: BinaryMarket, outcome: str) -> float:
        pos = self.pf.position(m.market_id)
        self.pf.cash += pos.yes if outcome == "YES" else pos.no
        pos.yes = pos.no = 0.0
        return self.pf.cash


# --------------------------------------------------------------------------- #
@dataclass
class StepTelemetry:
    mid: Optional[float]
    n_intents: int
    approved: int
    rejected: List[str]
    fills: int
    equity: float
    fill_list: List[Fill] = field(default_factory=list)


class PaperOMS:
    def __init__(self, strategy, risk_gate: RiskGate, broker: PaperBroker) -> None:
        self.strategy = strategy
        self.risk = risk_gate
        self.broker = broker
        self.equity: List[float] = []
        self.now = 0

    def step(self, m: BinaryMarket) -> StepTelemetry:
        step_fills: List[Fill] = []
        # 1. settle resting maker quotes against the new book
        for f in self.broker.settle_resting(m):
            self.strategy.on_fill(f)
            step_fills.append(f)
        # 2. strategy decides
        ctx = Context(now=float(self.now), markets={m.market_id: m},
                      portfolio=self.broker.pf)
        intents = self.strategy.on_tick(ctx)
        # 3. every intent passes the RiskGate before the broker sees it
        approved, rejected = 0, []
        for it in intents:
            ok, reason = self.risk.check(it, self.broker.pf, m)
            if not ok:
                rejected.append(reason)
                continue
            approved += 1
            for f in self.broker.execute(it, m):
                self.strategy.on_fill(f)
                step_fills.append(f)
        self.broker.replace_resting()
        # 4. mark to market
        eq = self.broker.mark_to_market(m)
        self.equity.append(eq)
        self.now += 1
        return StepTelemetry(m.yes_book.mid(), len(intents), approved, rejected,
                             len(step_fills), eq, step_fills)
