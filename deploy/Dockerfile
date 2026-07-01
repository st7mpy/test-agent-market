# Strategy-runner image — the deployable unit for one vault/strategy session.
# Build from the repo root:   docker build -f deploy/Dockerfile -t predmkt-runner .
# Run (offline replay):       docker run --rm predmkt-runner
# Run (own config):           docker run --rm -v $PWD/my.json:/config/config.json predmkt-runner
#
# The code is stdlib-only, so the image is just Python + the strategies tree.
FROM python:3.12-slim

# never run trading code as root
RUN useradd --create-home --shell /usr/sbin/nologin runner
USER runner
WORKDIR /app

COPY --chown=runner:runner strategies/ /app/
COPY --chown=runner:runner deploy/config.example.json /config/config.json

# secrets come from the environment, never the image:
#   POLYMARKET_ADDRESS  wallet address used for position reconciliation (optional)

# exit codes: 0 = clean session, 1 = config error, 2 = kill-switch halt (do NOT
# auto-restart on 2 — a reconciliation breach needs a human, ADR-011)
ENTRYPOINT ["python", "run.py", "--config", "/config/config.json"]
