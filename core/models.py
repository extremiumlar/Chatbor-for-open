"""SQLAlchemy ORM modellari — TZ 11-bo'lim (MVP-1 doirasida kerak bo'lgan jadvallar).

Adminbot hali yo'qligi uchun `templates` / `bot_patterns` / `audit_log`
jadvallari MVP-2 da qo'shiladi (TZ 15-bo'lim bosqichlariga rioya qilinmoqda).
"""

import datetime

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from core.enums import CaseStatus

# native_enum=False: SQLite'da oddiy VARCHAR sifatida saqlanadi (real ENUM
# turi shart emas), lekin O'QISHDA ham CaseStatus a'zosiga aylantirib beradi —
# plain String bo'lganda bazadan o'qilgan qiymat oddiy str bo'lib qolar edi
# (.value kabi enum-xos APIlar ishlamay qolardi, Adminbot `drop find`da sezildi).
_STATUS_TYPE = SqlEnum(CaseStatus, native_enum=False, length=32)


class Base(DeclarativeBase):
    pass


class Admin(Base):
    """MVP-1 da minimal: Teleton qaysi shaxsiy akkaunt ostida ishlayotgani.

    To'liq rol tizimi (owner/rop/dasturchi/admin/kuzatuvchi, TZ 14-bo'lim)
    Adminbot bilan birga MVP-2 da kengaytiriladi.
    """

    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(255))


class User(Base):
    """Mijoz — TZ 11.1."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    tg_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    assigned_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id"), nullable=True
    )
    is_safe: Mapped[bool] = mapped_column(default=True)
    is_blocked: Mapped[bool] = mapped_column(default=False)
    first_seen: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    cases: Mapped[list["Case"]] = relationship(back_populates="user")


class Bot(Base):
    """Tekshiruv boti (qora quti, pool a'zosi) — TZ 11.4."""

    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    is_busy: Mapped[bool] = mapped_column(default=False)
    current_case_id: Mapped[int | None] = mapped_column(
        ForeignKey("cases.id", use_alter=True), nullable=True
    )
    total_processed: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    # TZ 9.5 (Q53) — bot bilan raqam/kupon yuborish formati
    phone_format: Mapped[str] = mapped_column(String(32), default="+998XXXXXXXXX")

    # MVP-5 (Q55) — "har admin+bot juftligi mustaqil slot" xavfsiz standart:
    # None bo'lsa umumiy (bitta akkaunt) pool'ga tegishli, aks holda faqat
    # shu admin'ning Teleton sessiyasi ushbu botni ishlata oladi.
    owner_admin_id: Mapped[int | None] = mapped_column(ForeignKey("admins.id"), nullable=True)

    # MVP-5 (Q54) — ba'zi real botlar avval /start bosilishini talab qilishi
    # mumkin; /addbot orqali admin belgilaydi, real_bot_adapter shunga qarab
    # birinchi ishlatishda /start yuboradi.
    needs_start_greeting: Mapped[bool] = mapped_column(default=False)


class Case(Base):
    """Murojaat — TZ 11.2."""

    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    phone: Mapped[str] = mapped_column(String(32))
    current_coupon: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[CaseStatus] = mapped_column(_STATUS_TYPE, default=CaseStatus.NUMBER_RECEIVED)
    assigned_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id"), nullable=True
    )
    bot_id: Mapped[int | None] = mapped_column(ForeignKey("bots.id"), nullable=True)

    # TZ 2.1 (Q59) — EXPIRED-qayta-urinish sikli hisoblagichi, 5 marta
    # ketma-ket EXPIRED bo'lsa NEEDS_ADMIN'ga o'tadi (MVP-3).
    expired_attempts: Mapped[int] = mapped_column(Integer, default=0)

    # TZ 9.3 ("Qayta uzatish") — Adminbot Telethon'ga ega emas, shuning uchun
    # o'zi dispatch qila olmaydi. Admin "Qayta uzatish"ni bosganda shu bayroq
    # qo'yiladi, Teleton'ning fon kuzatuvchisi ko'rib dispatch qiladi va
    # bayroqni tozalaydi (SUSPICIOUS_HOLD -> is_safe bilan bir xil naqsh).
    # Aynan shu maqsadli bayroq ishlatiladi, NUMBER_RECEIVED holatini kuzatish
    # emas — chunki pool navbati Teleton jarayonining XOTIRASIDA, va o'sha
    # navbatda turgan case'lar ham NUMBER_RECEIVED bo'lib, ikki marta
    # dispatch qilinib ketardi.
    admin_redispatch_requested: Mapped[bool] = mapped_column(default=False)

    confirmed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="cases")
    attempts: Mapped[list["CouponAttempt"]] = relationship(back_populates="case")


class CouponAttempt(Base):
    """Kupon urinishlari tarixi — TZ 11.3 (Q61: kupon qiymati saqlanadi)."""

    __tablename__ = "coupon_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"))
    coupon: Mapped[str] = mapped_column(String(16))
    result: Mapped[CaseStatus] = mapped_column(_STATUS_TYPE)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    case: Mapped["Case"] = relationship(back_populates="attempts")


class Template(Base):
    """Mijozga yuboriladigan shablon — TZ 7.2, 11.5. Adminbot `/templates` orqali
    o'zgartiradi; core.logic.templates.DEFAULTS bilan boshlang'ich to'ldiriladi."""

    __tablename__ = "templates"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(2000))


class Setting(Base):
    """Umumiy kalit-qiymat tizim sozlamasi (masalan bildirishnoma batafsil
    rejimi, TZ 9.1) — Adminbot orqali o'zgartiriladi."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


class BotPattern(Base):
    """Tekshiruv botni TANISH shabloni — TZ 7.1 (9.4, Q16: to'liq
    kiritilmaguncha real bot rejimi ishga tushmaydi). Bularni core.texts'dagi
    mijozga yuboriladigan shablonlar bilan aralashtirmaslik kerak (TZ 7-bo'lim,
    Q47) — bular tekshiruv BOTNING o'z chiqishini tanish uchun, mijozga
    yuborilmaydi."""

    __tablename__ = "bot_patterns"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))


class AuditLog(Base):
    """Admin harakatlari tarixi — TZ 11.5, 12.2 (kim, qachon, nima qildi)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_tg_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(64))
    details: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
