FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc pkg-config && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p logs instance
ENV PYTHONUNBUFFERED=1 INSTANCE_DIR=/app/instance
EXPOSE 5000
# One worker: the weekly-report scheduler and the classic assistant keep state per process.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "--timeout", "120", "run:app"]
