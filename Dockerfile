FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY config.yaml .
COPY src/ src/
ENV PYTHONUNBUFFERED=1 TZ=Asia/Kolkata
CMD ["python", "src/uploader.py"]
