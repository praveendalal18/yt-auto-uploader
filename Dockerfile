FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Asia/Kolkata PORT=8080
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY config.yaml .
COPY src/ src/
COPY app/ app/
# Default: the web app (Cloud Run service). The CLI job overrides this with
#   --command python --args src/uploader.py   (see deploy/deploy_cloud_run.sh).
CMD exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips="*"
