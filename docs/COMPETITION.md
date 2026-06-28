# Competitive Intelligence

*Standalone competitor teardown (2026). Pairs with `DIFFERENTIATION.md` (what to build to win)
and `EVALUATION.md §6` (analogues). This doc is the "who's out there and how do we stack up."*

---

## 1. Market context

Prediction-market demand is validated and the trading-tooling layer is **already populated** — the
naïve "vault marketplace" is not white space. On-chain prediction volume ran ~$390M/month through
mid-2026 (Polymarket >96%), with a fast-growing periphery (Kalshi, Limitless, Myriad, Drift, Azuro).
Bots are >30% of Polymarket wallet activity and dominate the profit leaderboard. So: enter expecting
**occupied, partly-commoditized territory**, and differentiate on what incumbents structurally can't do.

---

## 2. Direct competitors (pooled-capital vaults on prediction markets)

These are the closest — same shape as the planned B-layer.

### Moneytalks — `moneytalks.market`
- **Model:** non-custodial Polymarket vaults; depositors put USDC behind a trader they choose.
- **Fees:** **0% management, 10% profit-only** performance fee. *(Note: this is the exact fee
  mechanic in our design — they got there first.)*
- **Strengths:** live, simple, non-custodial, on-chain-transparent performance, clean fee.
- **Lacks:** discretionary (human) traders not automated quant; **positions fully visible on-chain**
  (copyable / front-runnable); **no maker skin-in-the-game, slashing, or capacity caps**;
  Polymarket-only; no oracle-risk protection.
- **Threat:** **High** — it's the cleanest version of the core idea, already shipped.

### PolyFund — `polyzone.app/polyfund`
- **Model:** permissionless "prediction funds" run by forecasters; managers set their own terms.
- **Fees:** up to **3% deposit + up to 30% performance** — notably higher and less aligned than
  profit-only.
- **Strengths:** permissionless listing, visible per-fund record + total deposits.
- **Lacks:** same gaps as Moneytalks (discretionary, transparent positions, no alignment stack,
  single-venue); the deposit fee + 30% perf is a weaker depositor deal.
- **Threat:** **Medium-high** — proves the model but is more extractive and less aligned.

**Takeaway:** both validate demand and both leave the *same* four gaps open — automation/quant infra,
position privacy, the alignment stack (skin-in-game + slashing + caps), and oracle protection.

---

## 3. Adjacent competitors (by category)

| Category | Named players | What they do | Assessment |
|---|---|---|---|
| **Copy-trading bots** | PolyCopyTrade, FrenFlow, WhaleMirror, polycop, polygun, kreopolybot, polyapex, Telegram bots | Mirror profitable wallets; non-custodial (your wallet signs), sub-second on-chain detection, Kelly sizing, risk caps | Commoditized and crowded; lots of SEO/affiliate sites and inflated "127% profit" marketing. Different model (copy a wallet, not deposit to a managed vault). **Medium** |
| **AI agent platforms / app stores** | **Olas/Pearl + Polystrat/Omenstrat** (OLAS staking), **Virtuals** (15.8k agents), Elastics, Polytrader, Astron/Raven, Polyseer (OSS) | Autonomous agents that pick + trade markets; NLP goal-setting; token-incentivized distribution | Token flywheel = real distribution edge we lack; but mostly single-agent products/launchpads, hype-heavy, no alignment/insurance mechanics, on-chain-visible. **Medium-high** |
| **Per-venue bot tools (DIY)** | Kalshi: KalshiBot, Bot for Kalshi ($99/mo), Octagon/ryanfrigo/yllvar OSS; Polymarket: PolyCatalog (21 bots), Hummingbot | Run-your-own bot; pre-built strategy libraries (momentum/mean-reversion/news), visual builders | Picks-and-shovels; low switching cost; competes on "run your own" vs "deposit into one." **Medium** |
| **On-chain asset-management vaults** | **dHEDGE**, **Enzyme**, Morpho, Yearn | Non-custodial tokenized vaults; managers monetize edge; performance fees; composable | Crypto-asset/yield, *not* prediction markets — but the rails could extend here. **Latent platform risk** |
| **Crowdsourced-quant analogues** | Numerai, QuantConnect (Alpha Streams — deprecated), Darwinex, Collective2, eToro, 3Commas | Allocate capital to private/verified strategies (TradFi/crypto) | Not competitors; design analogues (esp. Numerai's private-models-staking model). **Low** |

---

## 4. The venues themselves (platform risk)

The two venues you depend on are also your biggest strategic risk.

- **Polymarket** — raised ~$2B (≈$9–20B valuations cited); owns >96% of on-chain volume, the
  leaderboard, and the API that the entire copy/agent ecosystem is built on. Could launch native
  copy/agents/vaults, or restrict API access. The maker-rebate + liquidity-reward programs you'd
  harvest are venue-controlled and can change.
- **Kalshi** — CFTC-regulated, **open API that natively supports automated trading** (no bot tier).
  Lower-friction for bots, but US-regulated and a different rail entirely.

**Implication:** build assuming the venue is a frenemy — don't let any single-venue dependency or
incentive program be load-bearing for the business.

---

## 5. Build-leverage, not just competition

The multi-venue aggregation layer is partly solved by open tooling you can **build on**:
- **pmxt** — OSS Python/TS SDK; local sidecar normalizing data + execution across Polymarket,
  Kalshi, Limitless.
- **agg.market** — aggregates Polymarket, Kalshi, Myriad, Limitless, Opinion (+ Hyperliquid).
- **PolyRouter** — unified REST across 7 venues (Polymarket, Kalshi, Manifold, Limitless, ProphetX,
  Novig, SX.bet).

These accelerate the `VenueAdapter` layer instead of forcing a from-scratch build.

---

## 6. Feature-comparison matrix

Legend: ✅ yes · ❌ no · ~ partial · — n/a. *"This project" columns are the **target** design, not shipped.*

| Capability | **This project (target)** | Moneytalks | PolyFund | Copy-bots | Olas/Pearl | dHEDGE/Enzyme |
|---|---|---|---|---|---|---|
| Pooled-capital vault | ✅ | ✅ | ✅ | ❌ (mirror) | ❌ (own agent) | ✅ |
| Non-custodial | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Automated / quant strategies | ✅ | ❌ (discretionary) | ❌ | ✅ | ✅ | ~ |
| **Private (un-copyable) positions** | ✅ (TEE) | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Verified track record** | ✅ (attested) | ✅ (public) | ✅ (public) | ~ | ~ | ✅ (public) |
| **Maker skin-in-game** (first-loss + bond) | ✅ | ❌ | ❌ | ❌ | ~ (stake) | ~ |
| Mechanical slashing | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Dynamic capacity caps | ✅ | ❌ | ❌ | ❌ | ❌ | ~ |
| **Venue-yield (maker-rebate) product** | ✅ | ❌ | ❌ | ❌ | ❌ | — |
| **Oracle-failure insurance** | ✅ | ❌ | ❌ | ❌ | ❌ | — |
| Multi-venue | ✅ (target) | ❌ | ❌ | ~ | ~ | — |
| Fee model | profit-only + HWM + tiers | 0% + 10% perf | ≤3% dep + ≤30% perf | sub / varies | token | mgmt + perf |
| Token | ❌ (by choice) | ❌ | ❌ | mostly ❌ | ✅ (OLAS) | ✅ (gov) |

The combination **no competitor has** is the moat: *private positions **and** verified track record
**and** the alignment stack **and** venue-yield **and** oracle insurance.* Individually each is
matchable; together they're the differentiated product (`DIFFERENTIATION.md §6`).

---

## 7. Threat assessment

| Threat | Level | Why | Response |
|---|---|---|---|
| Moneytalks / PolyFund | High | Already shipped the core vault | Differentiate on privacy + alignment + venue-yield + insurance, not the wrapper |
| Venue moves up-stack / gates API | High | Polymarket owns liquidity + API | Multi-venue; don't depend on one venue/incentive program |
| Token-incentivized agent app stores | Medium-high | Distribution flywheel we lack | B2B white-label + regulated/institutional wrapper as the non-token distribution answer |
| Copy-bot commoditization | Medium | Cheap, crowded | Compete on managed-vault + privacy, not on "follow smart money" |
| dHEDGE/Enzyme add prediction markets | Medium | Rails already exist | Speed + prediction-market-specific risk/oracle/venue-yield depth |

---

## Sources

- [Moneytalks](https://moneytalks.market/) · [PolyFund](https://polyzone.app/polyfund/)
- [Best Polymarket copy-trading bots (PolyCatalog, 21 tools)](https://www.polycatalog.io/polymarket-trading-bots) · [Polymarket copy-trading guide](https://polycopy.app/polymarket-copy-trading-bots)
- [Olas — Polystrat](https://olas.network/blog/introducing-polystrat-an-autonomous-ai-prediction-agent-on-polymarket) · [CoinDesk — AI agents rewriting prediction markets](https://www.coindesk.com/tech/2026/03/15/ai-agents-are-quietly-rewriting-prediction-market-trading) · [Virtuals overview](https://www.weex.com/news/detail/5-best-ai-agents-in-2026-a-beginners-guide-to-cryptos-autonomous-future-689701)
- [Kalshi bot tools](https://www.quicknode.com/builders-guide/best/top-10-kalshi-trading-tools-bots) · [Kalshi API docs](https://docs.kalshi.com/welcome)
- [dHEDGE](https://dhedge.org/) · [Enzyme](https://enzyme.finance/)
- [Prediction-market venues 2026](https://bingx.com/en/learn/article/what-are-the-top-decentralized-prediction-markets) · [agg.market aggregator](https://www.tradingview.com/news/chainwire:080c1c56f094b:0-snag-solutions-launches-agg-market-to-aggregate-prediction-markets-and-optimize-trade-pricing-across-venues/) · [Polymarket $2B raise](https://insights4vc.substack.com/p/polymarket-raises-2b-at-9b-valuation)
