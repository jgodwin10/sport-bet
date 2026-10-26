FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home --uid 10001 app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER app
EXPOSE 8000
# Migrations run on start (idempotent; compose also has a dedicated `migrate` service).
# Hosts like Render inject PORT. Set FORWARDED_ALLOW_IPS=* behind a trusted proxy so
# uvicorn uses X-Forwarded-For and rate limiting sees real client IPs.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
