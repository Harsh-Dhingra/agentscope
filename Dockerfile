FROM node:22-bookworm-slim AS ui
WORKDIR /build/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY agentscope/ agentscope/
COPY --from=ui /build/web/dist web/dist/
RUN pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home appuser && mkdir data && chown appuser data
USER appuser
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health')"
CMD ["python","-m","uvicorn","agentscope.api:app","--host","0.0.0.0","--port","8765"]
