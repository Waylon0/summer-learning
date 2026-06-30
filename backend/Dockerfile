FROM python:3.12-slim

WORKDIR /app

RUN pip install uv --quiet

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project 2>/dev/null || uv sync --no-dev

COPY . .

RUN mkdir -p data/uploads data/chroma logs

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
