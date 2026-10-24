FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY probe_app.py .
EXPOSE 8080
# --no-proxy-headers: uvicorn's own forwarded-header handling would hide what indah does.
CMD ["uvicorn", "probe_app:app", "--host", "0.0.0.0", "--port", "8080", "--no-proxy-headers"]
