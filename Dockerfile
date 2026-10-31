FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /code

# Install packages first, so code changes don't reinstall them
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY app ./app

# main.py finds templates/ relative to the working directory
WORKDIR /code/app

# Create the table if it is missing, then start the app
CMD ["sh", "-c", "uv run --no-sync database/create_tables.py && uv run --no-sync main.py"]
