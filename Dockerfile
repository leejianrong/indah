# Runs the built-in indah demo in a container. Installs from source using the
# committed pre-built shell (src/indah/static/index.html) -- no Node here, which
# is the whole point (ADR-0004). This is a dev/demo convenience; indah itself is
# just `pip install indah`, no container required.
FROM python:3.12-slim

WORKDIR /app

# Copy metadata + source needed to build the wheel, then install.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

# Bind all interfaces on a fixed port so the container is reachable (and
# routable by Traefik). See src/indah/__main__.py.
ENV INDAH_HOST=0.0.0.0 \
    INDAH_PORT=8000
EXPOSE 8000

CMD ["python", "-m", "indah"]
