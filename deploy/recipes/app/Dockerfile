# One image for both recipes. Build from this directory:
#   docker build -t my-indah-app deploy/recipes/app
# `INDAH_SPEC` is what pip installs. It must be a release that has /ready, the INDAH_* settings,
# the node header and the presets (the first release after 0.7.0). Until that is on PyPI, use
# deploy/recipes/build-image.sh, which installs a wheel built from your checkout instead.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
ARG INDAH_SPEC="indah"
WORKDIR /app
COPY . /app
RUN pip install "uvicorn[standard]" ${INDAH_SPEC}
# A numeric user, so Kubernetes can check runAsNonRoot.
RUN useradd --uid 10001 --no-create-home indah
USER 10001
EXPOSE 8080
# Exec form, so uvicorn is PID 1 and gets SIGTERM (indah drains on it). --no-proxy-headers: indah
# applies its own trusted_proxies rules, so uvicorn must not rewrite the client address first.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--no-proxy-headers"]
