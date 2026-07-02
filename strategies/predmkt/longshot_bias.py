"""Favorite-longshot bias harvester (clean-room).

The favorite-longshot bias is the best-documented pricing anomaly in betting and
prediction markets: longshots trade *above* their true probability and heavy
favorites *below* — retail demand for lottery-like payoffs pushes the tails out.
The harvest is always the same trade expressed from the favorite side: **buy the
favorite token** (equivalently, sell the overpriced tail) whenever the debiased
fair value still clears fees plus a margin.

Debiasing map (a logit-power stretch): with market probability p for a token,

    pi(p) = p^beta / (p^beta + (1-p)^beta),    beta > 1

pulls tails toward 0/1 (e.g. beta=1.4 maps a 5c longshot to ~1.6c true), leaving
mid-range prices nearly untouched. `beta` is the single empirical knob; calibrate
it per venue/category from resolved markets before sizing real capital.

This is a *portfolio* strategy with negative skew — each trade risks the favorite
price to win the tail — so the controls are the point:

  * act only in the tail zone (`longshot_max`), where the bias concentrates;
  * momentum guard: never sell a tail that is strengthening (that's news, not noise);
  * oracle-risk gate (optional `OracleRiskModel`): a disputed resolution is exactly
    the tail event being sold, so dispute-prone markets are excluded (ADR-014);
  * hard per-market risk budget and gross cap — sized so a full tail loss on any
    single market costs a bounded, pre-committed fraction of bankroll;
  * diversification: at most `max_entries_per_tick` new positions per tick.

Technique references (read-only, not copied): Thaler & Ziemba (1988) on the
favorite-longshot bias; Snowberg & Wolfers (2010) on misperception vs risk-love.
Original implementation.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional

from .base import Context, Strategy, depth_capped_size
from .fees import taker_fee_per_share
from .oracle_risk import OracleRiskModel
from .types import BinaryMarket, Intent, LimitOrder, Side, TIF, Token


def debias(p: float, beta: float) -> float:
    """Logit-power favorite-longshot correction: market prob -> estimated true prob."""
    p = max(0.0, min(1.0, p))
    if p in (0.0, 1.0) or beta == 1.0:
        return p
    num = p ** beta
    return num / (num + (1.0 - p) ** beta)


@dataclass
class LongshotParams:
    beta: float = 1.4                # tail-stretch exponent (calibrate per venue/category)
    longshot_max: float = 0.15       # act only when one side trades at or below this
    min_edge: float = 0.02           # required debiased edge after fees, per share
    risk_per_market: float = 0.02    # max bankroll fraction lost if the tail hits
    gross_cap: float = 0.30          # max bankroll fraction deployed by this strategy
    depth_fraction: float = 0.25     # cap size to 25% of fillable depth
    max_entries_per_tick: int = 3    # diversification: don't binge on one tick
    momentum_window: int = 30        # ticks of mid history for the news guard
    momentum_veto: float = 0.02      # skip if favorite lost this much over the window
    max_oracle_risk: float = 0.35    # refuse markets scoring above this (if model given)


class LongshotBiasStrategy(Strategy):
    name = "longshot_bias"

    def __init__(self, bankroll: float, params: LongshotParams | None = None,
                 oracle_model: Optional[OracleRiskModel] = None) -> None:
        self.bankroll = bankroll
        self.p = params or LongshotParams()
        self.oracle_model = oracle_model
        self._hist: Dict[str, Deque[float]] = {}

    # ------------------------------------------------------------------ #
    def _record(self, m: BinaryMarket) -> None:
        mid = m.yes_book.mid()
        if mid is not None:
            self._hist.setdefault(m.market_id, deque(maxlen=self.p.momentum_window)).append(mid)

    def _favorite_weakening(self, market_id: str, favorite: Token) -> bool:
        """True if the favorite side lost more than `momentum_veto` over the window —
        the tail is strengthening on news, and selling into that is how this
        strategy blows up."""
        h = self._hist.get(market_id)
        if not h or len(h) < 2:
            return False
        move = h[-1] - h[0]                       # signed YES-mid move
        fav_move = move if favorite == Token.YES else -move
        return fav_move < -self.p.momentum_veto

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
        entries = 0
        for m in ctx.markets.values():
            self._record(m)
            if entries >= self.p.max_entries_per_tick:
                break
            intent = self._consider(m, ctx)
            if intent is not None:
                out.append(intent)
                entries += 1
        return out

    def _consider(self, m: BinaryMarket, ctx: Context) -> Optional[LimitOrder]:
        mid = m.yes_book.mid()
        if mid is None:
            return None
        # which side is the tail?
        if mid <= self.p.longshot_max:
            favorite = Token.NO
        elif mid >= 1.0 - self.p.longshot_max:
            favorite = Token.YES
        else:
            return None                          # bias is a tail phenomenon; skip mid-range

        if self.oracle_model is not None and self.oracle_model.score(m) > self.p.max_oracle_risk:
            return None                          # dispute risk IS the tail we're selling
        if self._favorite_weakening(m.market_id, favorite):
            return None                          # tail strengthening on news — don't fade it

        ask = m.book(favorite).best_ask()
        if ask is None or ask >= 1.0:
            return None
        p_yes_true = debias(mid, self.p.beta)
        fair = p_yes_true if favorite == Token.YES else 1.0 - p_yes_true
        fee = taker_fee_per_share(m.venue, ask, m.category)
        edge = fair - ask - fee
        if edge < self.p.min_edge:
            return None

        # already holding this favorite? one bite per market
        pos = ctx.portfolio.position(m.market_id)
        held = pos.yes if favorite == Token.YES else pos.no
        if held > 0:
            return None

        # sizing: full loss (favorite -> 0) must cost <= risk_per_market of bankroll
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
            f"longshot fav={favorite.value} mid={mid:.3f} fair={fair:.3f} edge={edge:.3f}",
            m.market_id, favorite, Side.BUY, ask, shares, TIF.IOC)
