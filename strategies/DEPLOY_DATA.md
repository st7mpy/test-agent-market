# Running live Polymarket data from a supported region

Polymarket's public data endpoints (Gamma metadata, CLOB books + price history) are
**read-only and unauthenticated**, but they sit behind Cloudflare and are **geofenced** —
requests from some regions (e.g. India) or flagged datacenter IPs get `403`/`451`.

`predmkt/data.py` already sends browser-like headers (which clears the common *bare-client*
403). If you still get blocked, it's a **geographic/IP** block — run the fetch from a
supported region. This is also where the hosted bot belongs anyway (ARCHITECTURE ADR-001:
hosted execution, not a laptop).

> **Scope:** this is for **read-only market data** (research, backtests, paper trading) —
> fully legitimate. It is **not** a way to place real-money trades from a geofenced region;
> that's the offshore-entity + legal question in `HANDOFF.md §8`, not an infra toggle.

## Quick local test first

```bash
cd strategies
python check_polymarket.py          # OK => you're not blocked; skip the rest
```

If `BLOCKED`, pick any option below (all put you on a US/EU IP).

## Option A — Fly.io (cheapest always-on, ~2 min)

```bash
# one-time: install flyctl + `fly auth login`
cd strategies
fly launch --no-deploy --region iad        # iad = US-East (Ashburn)
# add a Dockerfile or use a python base; then run the check on the machine:
fly ssh console -C "python check_polymarket.py"
# or run a backtest on real data:
fly ssh console -C "python backtest.py --strategy mm --live --query 'election'"
```

Minimal `Dockerfile` (dependency-free — just Python + this folder):

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . /app
CMD ["python", "check_polymarket.py"]
```

## Option B — Render / Railway (dashboard, no CLI)

- New **Background Worker** (or one-off Job) from the repo, root = `strategies/`.
- Region: **US-East** or **EU**. Build: none. Start: `python check_polymarket.py`.
- Then change the start command to your `backtest.py --live` / `papertrade.py --source live` run.

## Option C — any US/EU VPS (AWS Lightsail / Hetzner / DO)

```bash
ssh you@your-us-vm
git clone <your-repo> && cd <repo>/strategies
python3 check_polymarket.py
python3 backtest.py --strategy mm --live --query "election"
```

## Knobs (env vars, honored by `predmkt/data.py`)

| Var | Effect |
|---|---|
| `PREDMKT_USER_AGENT` | Override the request User-Agent if a venue rotates its bot rules |
| `HTTPS_PROXY` | Route requests through a proxy in a supported region (alternative to a VM) |
| `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` | Custom CA bundle if your egress does TLS inspection |

## Once reachable

```bash
python check_polymarket.py                                   # expect REACHABLE
python backtest.py  --strategy mm  --live --query "election" # real price-replay
python papertrade.py --strategy arb --source live --query "election"
python live.py       --strategy mm --source live --query "election"
```

Then swap the bundled offline fixture for a fetched real series and re-run the Phase-0 tooling.
