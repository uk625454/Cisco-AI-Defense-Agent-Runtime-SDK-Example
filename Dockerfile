FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

COPY requirements.txt ./
RUN uv pip install --system -r requirements.txt

COPY agent.py ./
COPY config ./config

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8080"]
