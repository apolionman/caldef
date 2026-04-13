FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies first (layer cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Persistent volume mount point for the SQLite database
RUN mkdir -p /data

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Environment defaults (override in docker-compose or at runtime)
ENV DATABASE_PATH=/data/caldef.db \
    FLASK_APP=app.py \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 5050

# entrypoint.sh runs init_db once before Gunicorn starts,
# guaranteeing tables exist before any worker handles a request
ENTRYPOINT ["./entrypoint.sh"]
