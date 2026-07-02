"""Smart-money flow signal (clean-room) — a `SignalProvider` over public order flow.

On Polymarket every fill settles on-chain, so *who traded what at which price* is
public. That makes a strategy available nowhere in traditional markets at retail:
score wallets by their **realized, resolved track record**, then tilt fair value
toward where the proven wallets are positioned right now.

Two stages, both dependency-free:

  1. `score_wallets(trades, outcomes)` — every historical trade on a *resolved*
     market is converted to a signed YES exposure at an implied YES price, and a
     wallet's raw edge is its size-weighted realized profit per share. Small
     samples are shrunk toward zero skill by n/(n+k) (a wallet with 3 lucky
     trades scores near zero; sustained edge survives), so skill must be earned.
  2. `SmartMoneyProvider` — given wallet scores and the *current* flow in a
     market, computes a skill-weighted net conviction in [-1, +1] and tilts the
     market's own microprice by at most `max_tilt`. No smart flow, no tilt: the
     provider degrades to the market-implied null model.

The provider obeys the signal-layer rules (ADR-012/013): it runs off the hot
path, only proposes probabilities, and must pass `evaluate_provider`'s Brier
skill + calibration gate on resolved markets before it is allowed to size
capital through the Kelly strategy (`as_fair_value_fn`).

Live wiring: the Polymarket Data API (`data-api.polymarket.com/trades`) exposes
per-fill maker/taker addresses, prices, and sizes; a nightly job replays resolved
markets through `score_wallets` and refreshes the score table. Untestable in this
session (egress blocked) — everything here runs on fixtures.

Technique references (read-only, not copied): copy-trading literature; Polymarket
wallet-tracker community tools (public leaderboards). Original implementation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .signals import Signal, SignalProvider
from .types import BinaryMarket, Side, Token


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ─────────────────────────── flow + scoring ──────────────────────────────────

@dataclass
class FlowTrade:
    """One observed fill, attributed to a wallet."""
    wallet: str
    market_id: str
    token: Token
    side: Side
    price: float          # price of `token` (NOT always the YES price)
    size: float           # shares


def signed_yes_exposure(t: FlowTrade) -> Tuple[float, float]:
    """Normalize any fill to (signed_yes_shares, implied_yes_price).

    BUY YES  = long YES at p;      SELL YES = short YES at p;
    BUY NO   = short YES at 1-p;   SELL NO  = long YES at 1-p.
    """
    if t.token == Token.YES:
        yes_price = t.price
        sign = 1.0 if t.side == Side.BUY else -1.0
    else:
        yes_price = 1.0 - t.price
        sign = -1.0 if t.side == Side.BUY else 1.0
    return sign * t.size, yes_price


@dataclass
class WalletScore:
    wallet: str
    n_trades: int
    raw_edge: float       # size-weighted realized profit per share, in [-1, 1]
    skill: float          # raw_edge shrunk by n/(n+k) — the number consumers use


def score_wallets(trades: Iterable[FlowTrade], outcomes: Mapping[str, int],
                  shrinkage_k: float = 20.0) -> Dict[str, WalletScore]:
    """Score wallets on resolved markets only (`outcomes[market_id]` in {0,1}).

    Realized edge per share of a normalized position is
    `sign * (outcome - implied_yes_price)`; a wallet's raw edge is the
    size-weighted mean over its resolved trades. Shrinkage n/(n+k) keeps small
    samples honest — with k=20, ten trades keep a third of their measured edge.
    """
    weight: Dict[str, float] = {}
    profit: Dict[str, float] = {}
    count: Dict[str, int] = {}
    for t in trades:
        y = outcomes.get(t.market_id)
        if y is None:
            continue                            # unresolved — not scoreable
        signed, yes_px = signed_yes_exposure(t)
        if signed == 0.0:
            continue
        edge = (1.0 if signed > 0 else -1.0) * (float(y) - yes_px)
        w = abs(signed)
        weight[t.wallet] = weight.get(t.wallet, 0.0) + w
        profit[t.wallet] = profit.get(t.wallet, 0.0) + w * edge
        count[t.wallet] = count.get(t.wallet, 0) + 1
    out: Dict[str, WalletScore] = {}
    for wallet, w in weight.items():
        n = count[wallet]
        raw = profit[wallet] / w if w > 0 else 0.0
        out[wallet] = WalletScore(wallet, n, raw, raw * (n / (n + shrinkage_k)))
    return out


# ─────────────────────────── the provider ────────────────────────────────────

@dataclass
class SmartMoneyParams:
    min_skill: float = 0.01              # ignore wallets below this shrunk skill
    max_tilt: float = 0.08               # max |p - microprice| the flow can justify
    full_conviction_notional: float = 10_000.0   # smart notional for full confidence
    recent_flow_window: int = 500        # keep at most this many fills per market


class SmartMoneyProvider(SignalProvider):
    """Tilts the market microprice toward proven wallets' current positioning."""
    name = "smart_money_flow"

    def __init__(self, wallet_scores: Mapping[str, WalletScore],
                 params: SmartMoneyParams | None = None) -> None:
        self.scores = dict(wallet_scores)
        self.p = params or SmartMoneyParams()
        self._flows: Dict[str, List[FlowTrade]] = {}

    def observe(self, trade: FlowTrade) -> None:
        """Feed a current-flow fill (from the live trade feed or a fixture)."""
        q = self._flows.setdefault(trade.market_id, [])
        q.append(trade)
        if len(q) > self.p.recent_flow_window:
            del q[: len(q) - self.p.recent_flow_window]

    def fair_value(self, m: BinaryMarket) -> Optional[Signal]:
        mp = m.yes_book.microprice()
        if mp is None:
            return None
        net, gross = 0.0, 0.0
        for t in self._flows.get(m.market_id, []):
            sc = self.scores.get(t.wallet)
            if sc is None or sc.skill < self.p.min_skill:
                continue
            signed, yes_px = signed_yes_exposure(t)
            notional = abs(signed) * yes_px
            net += sc.skill * (notional if signed > 0 else -notional)
            gross += sc.skill * notional
        if gross <= 0.0:
            # no qualified smart flow: fall back to the market itself, zero confidence
            return Signal(p=_clamp01(mp), confidence=0.0,
                          rationale="no qualified smart flow; market-implied")
        conviction = net / gross                                   # in [-1, 1]
        # scale confidence by how much proven-wallet money is actually behind it
        smart_notional = sum(
            abs(signed_yes_exposure(t)[0]) * signed_yes_exposure(t)[1]
            for t in self._flows.get(m.market_id, [])
            if (s := self.scores.get(t.wallet)) is not None and s.skill >= self.p.min_skill
        )
        confidence = min(1.0, smart_notional / self.p.full_conviction_notional)
        p = _clamp01(mp + self.p.max_tilt * conviction * confidence)
        return Signal(
            p=p, confidence=confidence,
            rationale=(f"smart-money conviction={conviction:+.2f} "
                       f"notional=${smart_notional:,.0f} tilt={p - mp:+.4f}"))
