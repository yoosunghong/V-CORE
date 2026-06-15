FROM python:3.12-slim

WORKDIR /app

COPY scripts ./scripts
COPY seeds ./seeds

CMD ["python", "scripts/seed_demo_data.py"]
