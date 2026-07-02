# Deploying the strategy runner

The deployable unit is one container running `strategies/run.py` against one JSON
config: **one session = one market = one strategy = one risk budget**. Everything a
session does is declared in the config; secrets come from the environment; the session
ends with a machine-readable report and a meaningful exit code.

```
config.json ──▶ run.py ──▶ VenueAdapter ──▶ Strategy ──▶ RiskGate ──▶ PaperBroker
                              ▲                                          │
                              └────── reconcile-or-halt (ADR-011) ◀──────┘
                                            │
                              session_report.json + exit code
```

## Quick start

```bash
# no Docker: dependency-free Python
cd strategies
python run.py --config ../deploy/config.example.json

# Docker (from the repo root)
docker build -f deploy/Dockerfile -t predmkt-runner .
docker run --rm predmkt-runner                                   # bundled replay config
docker run --rm -v $PWD/my.json:/config/config.json \
           -e POLYMARKET_ADDRESS=0xYourAddress predmkt-runner    # your session
```

## The config

See [`config.example.json`](config.example.json). Keys:

| Key | Meaning |
|---|---|
| `mode` | `replay` (bundled offline fixture; runs anywhere) or `live` (poll real venue books; **paper execution** — see below) |
| `venue`, `market` | `polymarket` + `{"query": ...}` or `kalshi` + `{"ticker": ...}` |
| `strategy.name` | `mm`, `kelly`, `arb`, `longshot`, `theta` |
| `strategy.params` | overrides for that strategy's params dataclass — unknown fields are rejected, so typos fail fast |
| `bankroll` | session capital (paper) |
| `risk` | `RiskLimits`: position/notional caps, `max_oracle_risk` to gate dispute-prone markets (ADR-014) |
| `oracle` | per-market `flags` / score `overrides` feeding the `OracleRiskModel`. Omitting it does NOT ungate `longshot`/`theta` — they always get a default category-based model (a note is printed); loosen explicitly via `strategy.params.max_oracle_risk` if you really mean it |
| `loop` | steps, reconciliation cadence, poll interval |
| `report_path` | where the session report JSON is written |

Relation arbitrage and cross-venue arbitrage need a multi-market feed and are not in
the single-market runner yet; they run through `multivenue_demo.py`-style harnesses.

## Exit codes (supervisor contract)

| Code | Meaning | Supervisor action |
|---|---|---|
| 0 | clean session end | restart / schedule next session freely |
| 1 | config error | fix config; do not retry as-is |
| 2 | **kill-switch halt** — positions diverged from venue truth (ADR-011) | **page a human; never auto-restart** |

`compose.yaml` encodes this with `restart: "no"`.

## Secrets

Nothing secret goes in the config or the image. Today the only credential is
optional: `POLYMARKET_ADDRESS` (wallet address for position reconciliation — an
address, not a key). Strategy code can never hold signing keys by design (ADR-002);
when real execution lands, keys live in the platform's KMS-backed OMS, not here.

## The two framings (same artifact)

**Platform-hosted (the product, B-on-C).** The platform runs one runner container per
vault on sandboxed infra. The config is generated from the vault's mandate (category
allowlist, caps, oracle policy = the depositor-facing risk disclosures), the report
feeds the public track record, and exit code 2 pages the operator. Makers never see
keys; depositors never run anything.

**Self-hosted (power users).** The identical image runs anywhere Docker runs. Users
supply their own config and watch their own reports. This is deliberately supported
but not the product: self-hosting gets you paper/live-data sessions and the strategy
library, not the vault stack (custody, fees, attestation, insurance).

## What "live" does NOT do yet

`mode=live` polls real books and reconciles positions, but fills are **simulated by
the paper broker**. Real order placement (EIP-712 signing on Polymarket, RSA-keyed
orders on Kalshi) is a Phase-1 platform component, gated by the plan's money-exposure
ladder (PLAN.md) — it is intentionally absent from this repository's strategy-adjacent
code. Do not point this at real capital expectations; the Phase-0 gate (documented
positive net real-money edge) has not been passed.
