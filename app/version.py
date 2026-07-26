"""Текущая версия программы — сверяется с version.json на GitHub Releases при проверке
обновлений (см. app/update_checker.py) и подставляется в установщик Inno Setup
(installer/ryatuvalnychok.iss читает эту строку через препроцессор при сборке)."""
__version__ = "1.0.0"
