FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
# indah is installed from a wheel that deploy.sh builds from this checkout, so the probe runs the
# code under test (the deploy doctor is newer than the last PyPI release).
COPY wheels/ /wheels/
RUN pip install --no-cache-dir /wheels/indah-*.whl "uvicorn[standard]"
COPY probe_app.py .
EXPOSE 8080
# --no-proxy-headers: uvicorn's own forwarded-header handling would hide what indah does.
CMD ["uvicorn", "probe_app:app", "--host", "0.0.0.0", "--port", "8080", "--no-proxy-headers"]
