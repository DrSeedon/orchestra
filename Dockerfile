FROM python:3.12-slim

# Install system deps: git, curl, Node.js 22
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Claude CLI globally
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

# Install Python deps (cached layer — only re-runs if pyproject.toml/uv.lock changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY app/ ./app/
COPY pipelines/ ./pipelines/
COPY workers/ ./workers/

# Ensure data dirs exist (volumes will overlay these)
RUN mkdir -p data worktrees

# Git identity required for worktree operations inside the container
RUN git config --global user.email "orchestra@localhost" \
    && git config --global user.name "Orchestra"

EXPOSE 8888

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8888"]
