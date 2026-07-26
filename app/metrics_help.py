"""
Глоссарий метрик дашборда — статический справочный контент (не пользовательские данные,
поэтому лежит рядом с кодом в app/, а не в data/). Хранится отдельным JSON-файлом на каждый
язык (metrics_help.json — ru, metrics_help_uk.json — uk), чтобы легко дополнять новыми
метриками или переводить, не трогая код.
"""
import json
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
METRICS_HELP_PATHS = {
    "ru": os.path.join(APP_DIR, "metrics_help.json"),
    "uk": os.path.join(APP_DIR, "metrics_help_uk.json"),
}


def load_metrics_help(lang: str = "ru") -> dict:
    path = METRICS_HELP_PATHS.get(lang, METRICS_HELP_PATHS["ru"])
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
