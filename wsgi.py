"""
Точка входу для gunicorn на Railway (Procfile: web: ... gunicorn wsgi:app ...).

create_app() — фабрика (Flask factory pattern), не готовий об'єкт застосунку, а gunicorn
очікує готовий WSGI-callable під фіксованим ім'ям у модулі. Локальна розробка (flask run,
python run.py) як і раніше йде через create_app() напряму — цей файл лише для gunicorn.
"""
from app import create_app

app = create_app()
