"""Muhit o'zgaruvchilaridan (.env) tizim sozlamalarini yuklaydi."""

import os
import secrets
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return value.strip().lower() in ("1", "true", "yes", "on") if value else default


def _list_env(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # Telethon (Teleton)
    api_id: int = _int_env("API_ID", 0)
    api_hash: str = os.getenv("API_HASH", "")
    session_name: str = os.getenv("SESSION_NAME", "my_account")

    # Baza
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data_relay.db")

    # TZ 2.2 (Q48) — mijoz kupon yubormasa necha soniyada seans to'xtaydi
    customer_coupon_timeout_seconds: int = field(
        default_factory=lambda: _int_env("CUSTOMER_COUPON_TIMEOUT_SECONDS", 300)
    )

    # TZ 4.1 (Q46) — haqiqiy O'zbekiston operator kodlari ro'yxati
    uz_operator_codes: list[str] = field(
        default_factory=lambda: _list_env(
            "UZ_OPERATOR_CODES",
            ["90", "91", "93", "94", "95", "97", "98", "99", "33", "88", "20"],
        )
    )

    # MVP-1: mock bot pool'ini boshlang'ich to'ldirish uchun slot nomlari
    # (real botlarga ulanganda MVP-5'da /addbot orqali almashtiriladi).
    bot_pool_usernames: list[str] = field(
        default_factory=lambda: _list_env(
            "BOT_POOL_USERNAMES",
            ["mock_bot_1", "mock_bot_2", "mock_bot_3", "mock_bot_4", "mock_bot_5"],
        )
    )

    # MVP-2: Adminbot (aiogram) — @BotFather'dan olingan token.
    adminbot_token: str = os.getenv("ADMINBOT_TOKEN", "")

    # MVP-2 (TZ 12.2) — boshlang'ich admin Telegram ID-lari (vergul bilan).
    # Adminbot ishga tushganda `admins` jadvaliga urug'lanadi (idempotent).
    admin_tg_ids: list[int] = field(
        default_factory=lambda: [int(x) for x in _list_env("ADMIN_TG_IDS", [])]
    )

    # MVP-3 (TZ 12-bo'lim) — tekshiruv bot javob bermasa necha marta va
    # qancha kutib qayta urinish (backoff: har urinishda ikki baravar oshadi).
    bot_response_max_retries: int = field(
        default_factory=lambda: _int_env("BOT_RESPONSE_MAX_RETRIES", 3)
    )
    bot_response_backoff_seconds: float = field(
        default_factory=lambda: _float_env("BOT_RESPONSE_BACKOFF_SECONDS", 1.0)
    )

    # MVP-3 (TZ 5.2) — shubhali holat "Xavfsiz" deb belgilangach, Teleton
    # navbatdagi case'ni necha soniyada bir tekshirib dispatch qiladi
    # (adminbot alohida jarayon bo'lgani uchun to'g'ridan-to'g'ri chaqira olmaydi).
    suspicious_resume_poll_seconds: float = field(
        default_factory=lambda: _float_env("SUSPICIOUS_RESUME_POLL_SECONDS", 3.0)
    )

    # MVP-4 (TZ 13-bo'lim, Q60) — kunlik avtomatik SQLite backup.
    backup_dir: str = os.getenv("BACKUP_DIR", "./backups")
    backup_interval_seconds: float = field(
        default_factory=lambda: _float_env("BACKUP_INTERVAL_SECONDS", 86400.0)
    )
    backup_retention: int = field(default_factory=lambda: _int_env("BACKUP_RETENTION", 14))

    # MVP-4 (TZ 12.1) — strukturali log fayllar papkasi.
    log_dir: str = os.getenv("LOG_DIR", "./logs")

    # MVP-5 — real tekshiruv botlariga ulanish (standart: False, mock bot
    # bilan davom etadi). True qilishdan oldin bot-tanish shablonlari
    # to'liq kiritilgan bo'lishi shart (TZ 9.4, Q16) — aks holda tizim STOP.
    use_real_verification_bots: bool = field(
        default_factory=lambda: _bool_env("USE_REAL_VERIFICATION_BOTS", False)
    )

    # MVP-6 — Web panel (FastAPI + Telegram Login Widget, TZ 13-bo'lim).
    # Bot username Adminbot bilan BIR XIL bo'lishi shart — widget shu bot
    # nomidan login qiladi (@BotFather -> /setdomain shu botga sozlanishi kerak).
    adminbot_username: str = os.getenv("ADMINBOT_USERNAME", "")
    panel_host: str = os.getenv("PANEL_HOST", "0.0.0.0")
    panel_port: int = field(default_factory=lambda: _int_env("PANEL_PORT", 8000))
    # Sozlanmasa har ishga tushirishda tasodifiy — seanslar restart'da
    # bekor bo'ladi (dev uchun qabul qilinadi, production'da .env'da o'rnating).
    panel_session_secret: str = os.getenv("PANEL_SESSION_SECRET") or secrets.token_urlsafe(32)


settings = Settings()
