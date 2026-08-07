web: flask db upgrade && gunicorn wsgi:app --workers 1 --worker-class gthread --threads 8 --timeout 120 --bind 0.0.0.0:${PORT:-8000}
release: flask db upgrade
