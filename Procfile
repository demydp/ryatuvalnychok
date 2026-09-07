# Railway/Heroku-style Procfile — legacy, Render його НЕ читає (Render Start Command і
# Pre-Deploy Command задаються вручну в Dashboard, див. .env.example і DEPLOY-інструкцію
# власника). Лишений на випадок повернення на Railway/Heroku.
web: flask db upgrade && gunicorn wsgi:app --workers 1 --worker-class gthread --threads 8 --timeout 120 --bind 0.0.0.0:${PORT:-8000}
release: flask db upgrade
