# One indah replica for the multi-replica e2e (IND-211). Build context is the repository root, so
# the image runs the code under test, with the Redis extra.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[redis]"
WORKDIR /app
COPY deploy/multireplica/app.py .
EXPOSE 8000
# --no-proxy-headers: only indah's own rules are under test. SIGTERM drains (IND-201).
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
