"""Telegram Login Widget tasdiqlash — TZ 13-bo'lim (Web panel).

⚠️ MUHIM: bu funksiya Telegram'ning rasmiy hujjatlashtirilgan algoritmi
bo'yicha yozilgan (https://core.telegram.org/widgets/login#checking-authorization),
lekin HAQIQIY Telegram'dan kelgan redirect bilan sinalmagan — Telegram Login
Widget ishlashi uchun bot @BotFather'da `/setdomain` orqali REAL, ochiq HTTPS
domenga bog'lanishi shart, bu esa ushbu ishlab chiqish muhitida mavjud emas.
Pastdagi `verify_telegram_auth` — sof funksiya, tarmoqqa bog'liq emas —
to'liq testlangan (soxta, ammo algoritmik jihatdan to'g'ri imzolangan
ma'lumotlar bilan). Ishlab chiqarishga chiqarishdan oldin haqiqiy domen bilan
qo'lda tekshirib ko'rish SHART.
"""

import hashlib
import hmac
import time


def verify_telegram_auth(
    data: dict, bot_token: str, max_age_seconds: int = 86400, now: int | None = None
) -> bool:
    """Telegram Login Widget'dan kelgan `data` (id, first_name, ..., auth_date,
    hash) to'g'ri va eskirmagan ekanligini tekshiradi."""
    data = dict(data)
    received_hash = data.pop("hash", None)
    if not received_hash:
        return False

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, str(received_hash)):
        return False

    try:
        auth_date = int(data.get("auth_date", 0))
    except (TypeError, ValueError):
        return False

    current_time = now if now is not None else int(time.time())
    if current_time - auth_date > max_age_seconds:
        return False

    return True
