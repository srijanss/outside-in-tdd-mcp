FROM python:3.12-slim
WORKDIR /mcp
COPY pyproject.toml /mcp/
COPY core/ /mcp/core/
RUN pip install --no-cache-dir "pytest" "pytest-json-report" /mcp
COPY adapters/pytest-adapter/run.sh /adapters/pytest-adapter/run.sh
RUN chmod +x /adapters/pytest-adapter/run.sh
ENV TDD_PROJECT_ROOT=/app
ENV TDD_CONFIG_PATH=/app/.tdd-config.json
ENTRYPOINT ["outside-in-tdd-mcp"]
