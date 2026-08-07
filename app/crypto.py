"""
Шифрування секретів (IG access token, Anthropic API-ключі) перед записом у БД (Этап 1 веб-версії).

Раніше (desktop, JSON-файли) ключі лежали в config.json/projects.json відкритим текстом — це
було прийнятно, бо файл живе тільки на машині власника. У багатокористувацькій веб-версії БД
спільна (Railway Postgres), тому секрети шифруються симетрично (Fernet, AES-128-CBC + HMAC) —
навіть прямий доступ до БД (дамп, витік креденшів БД) не розкриває чужі токени/ключі.

Ключ шифрування — ENCRYPTION_KEY (одна змінна оточення на весь застосунок, НЕ в БД і НЕ в
репозиторії) — Fernet-ключ (32 байти, urlsafe-base64). Втрата ENCRYPTION_KEY означає втрату
можливості розшифрувати всі секрети в БД (навмисно: інакше ключ шифрування довелося б зберігати
поряд із зашифрованими даними, що зводить шифрування нанівець) — тому генерується один раз при
розгортанні (generate_key()) і кладеться в .env/Railway-змінні, НІКОЛИ не логується.
"""
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("reels_dashboard")

_fernet = None


class CryptoConfigError(Exception):
    """ENCRYPTION_KEY не задано або невалідний — чесна помилка при старті, а не тихий провал
    шифрування (мовчки зберігати секрети відкритим текстом було б гірше, ніж впасти)."""


def generate_key() -> str:
    """Одноразова генерація нового Fernet-ключа для .env/Railway — див. модульний docstring."""
    return Fernet.generate_key().decode("ascii")


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise CryptoConfigError(
            "ENCRYPTION_KEY не задано в оточенні — секрети (IG-токени, Anthropic-ключі) "
            "неможливо ні зашифрувати, ні розшифрувати. Згенеруйте ключ: "
            "python -c \"from app.crypto import generate_key; print(generate_key())\" "
            "і додайте його як ENCRYPTION_KEY у .env / Railway variables."
        )
    try:
        _fernet = Fernet(key.encode("ascii"))
    except (ValueError, TypeError) as e:
        # Помилку логуємо без самого значення ключа — навіть невалідний ключ не повинен
        # потрапити в лог.
        logger.error("ENCRYPTION_KEY невалідний (не Fernet-ключ) — деталі приховано з логу")
        raise CryptoConfigError("ENCRYPTION_KEY невалідний — очікується 32-байтний urlsafe-base64 Fernet-ключ") from e
    return _fernet


def encrypt(plaintext: str | None) -> str | None:
    """Порожній рядок/None лишаємо як є (немає що шифрувати, і не хочемо зберігати "шифротекст
    порожнього рядка" — це ускладнило б перевірки on `if not token`)."""
    if not plaintext:
        return plaintext
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return ciphertext
    try:
        return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        # ENCRYPTION_KEY змінили/він не збігається з тим, яким шифрували — чесно "немає
        # значення", а не падіння всього запиту через один непрочитний секрет.
        logger.error("Не вдалося розшифрувати збережений секрет (невірний ENCRYPTION_KEY?) — повертаю порожнє значення")
        return ""
