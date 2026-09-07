FROM python:3.12-slim
WORKDIR /mcp
# nodejs/npm here are whatever version Debian's apt repo ships (untied to
# any consumer project's pinned Node version) — needed so the vitest
# adapter's `npx vitest` has a node/npm to run at all.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml /mcp/
COPY core/ /mcp/core/
# pytest/pytest-json-report are baked in at this fixed version, not read
# from the consumer project's own pin — unlike vitest (invoked via `npx`,
# which resolves the project's own local node_modules/devDependency first),
# a mounted project's pytest version may not match this image's. If a
# project needs a different pytest version, rebuild this image with that
# version pinned here manually (or install/run outside-in-tdd-mcp directly
# in the project's own venv instead of via Docker).
RUN pip install --no-cache-dir "pytest" "pytest-json-report" /mcp
COPY adapters/pytest-adapter/run.sh /adapters/pytest-adapter/run.sh
COPY adapters/vitest-adapter/run.sh /adapters/vitest-adapter/run.sh
RUN chmod +x /adapters/pytest-adapter/run.sh /adapters/vitest-adapter/run.sh
ENV TDD_PROJECT_ROOT=/app
ENV TDD_CONFIG_PATH=/app/.tdd-config.json
ENTRYPOINT ["outside-in-tdd-mcp"]
