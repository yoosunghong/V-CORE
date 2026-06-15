FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests

# HTTP health/debug on 8030; UDP 9999 + TCP 9998 for telemetry ingest.
EXPOSE 8030
EXPOSE 9999/udp
EXPOSE 9998
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8030"]
