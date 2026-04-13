#!/bin/sh
set -e

echo "Initialising database at ${DATABASE_PATH:-caldef.db} ..."
python3 -c "from database import init_db; init_db()"
echo "Database ready."

exec gunicorn \
  --bind 0.0.0.0:5050 \
  --workers 2 \
  --timeout 360 \
  --access-logfile - \
  --error-logfile - \
  app:app
