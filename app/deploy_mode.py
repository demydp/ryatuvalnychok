"""Єдина ознака «веб-деплой (Railway) vs десктоп-збірка», якою вже керується вибір БД
(app/db.py::get_database_uri) і прод-налаштування Flask (app/__init__.py::_is_production).
DATABASE_PUBLIC_URL/DATABASE_URL заданий лише на Railway — ніколи в десктопній збірці чи
локальній розробці (flask run без піднятого Postgres).
"""
import os


def is_web_deployment() -> bool:
    return bool(os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL"))
