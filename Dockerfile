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

# Environment defaults (override in docker-compose or at runtime)
ENV DATABASE_PATH=/data/caldef.db \
    FLASK_APP=app.py \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 5050

# Gunicorn: 2 workers, 120 s timeout (AI calls can be slow)
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5050", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
