"""SQLAlchemy ORM modellari — TZ 11-bo'lim (MVP-1 doirasida kerak bo'lgan jadvallar).

Adminbot hali yo'qligi uchun `templates` / `bot_patterns` / `audit_log`
jadvallari MVP-2 da qo'shiladi (TZ 15-bo'lim bosqichlariga rioya qilinmoqda).
"""

import datetime
import enum

from sqlalchemy import (
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from core.enums import CaseStatus

# native_enum=False: SQLite'da oddiy VARCHAR sifatida saqlanadi (real ENUM
# turi shart emas), lekin O'QISHDA ham CaseStatus a'zosiga aylantirib beradi —
# plain String bo'lganda bazadan o'qilgan qiymat oddiy str bo'lib qolar edi
# (.value kabi enum-xos APIlar ishlamay qolardi, Adminbot `drop find`da sezildi).
_STATUS_TYPE = SqlEnum(CaseStatus, native_enum=False, length=32)


class Base(DeclarativeBase):
    pass


class AdminRole(str, enum.Enum):
    """TZ 14-bo'lim — rollar. Audit K-4/J-8: avval bu tizim umuman yo'q edi,
    har bir `admins` qatoridagi odam cheklovsiz to'liq huquqqa ega edi."""

    OWNER = "OWNER"
    ROP = "ROP"
    DASTURCHI = "DASTURCHI"
    ADMIN = "ADMIN"
    KUZATUVCHI = "KUZATUVCHI"


# TZ 11.0 (Q51 — TASDIQLANGAN): faqat shu ikki rol boshqa adminlarning
# mijozlari/case'larini ham ko'ra oladi — qolganlari faqat o'ziga
# biriktirilganini (yoki hali hech kimga biriktirilmaganini) ko'radi.
UNRESTRICTED_ROLES = frozenset({AdminRole.OWNER, AdminRole.ROP})


class Admin(Base):
    """Adminbot/Panelga kira oladigan xodim — TZ 12.2, 14-bo'lim (rol)."""

    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[AdminRole] = mapped_column(
        SqlEnum(AdminRole, native_enum=False, length=16), default=AdminRole.ADMIN
    )

    # Kim kimligini aniq ko'rsatish uchun: seed paytida `name` faqat raqamli
    # tg_id bo'ladi ("6644467393"), bu esa ro'yxatda hech narsa anglatmaydi.
    # Admin bot bilan har muloqotda bu maydonlar Telegram'dagi joriy ism va
    # username bilan yangilanadi (`refresh_admin_identity`).
    tg_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # TZ v2 4.2b — admin "nofaol" deb belgilansa uning ochiq case'lari
    # muzlatiladi va Telethon klienti ishga tushirilmaydi.
    is_active: Mapped[bool] = mapped_column(default=True)

    # TZ v2 8.4 — superadmindan tashqari "hammani ko'rish" huquqi berilgan
    # kuzatuvchi adminlar (oddiy admin faqat o'z statistikasini ko'radi).
    can_view_all_stats: Mapped[bool] = mapped_column(default=False)


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

    # Audit J-4 — Adminbot va Teleton alohida jarayon (TZ 13.1); Adminbotning
    # "Majburan bo'shatish" tugmasi haqiqiy (jarayon-ichidagi) navbat
    # mexanizmiga to'g'ridan-to'g'ri tegina olmaydi. `admin_redispatch_requested`
    # bilan bir xil naqsh: Adminbot faqat shu bayroqni qo'yadi, Teleton'ning
    # fon kuzatuvchisi ko'rib HAQIQIY `BotPoolManager.force_release`ni
    # chaqiradi va bayroqni tozalaydi.
    force_release_requested: Mapped[bool] = mapped_column(default=False)


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

    # ------------------------------------------------------------------ #
    # TZ v2 — qo'lda admin oqimi maydonlari
    # ------------------------------------------------------------------ #

    # TZ v2 9.2 — guruh caption va qidiruv uchun qisqa kod ("C1247").
    # id ma'lum bo'lgach (birinchi flush'dan keyin) manual_case to'ldiradi.
    short_code: Mapped[str | None] = mapped_column(String(16), nullable=True, unique=True)

    # TZ v2 9.2 — kupon TEKSHIRUVGA ISHLATILMAYDI, lekin saqlanadi:
    # (1) mijoz holati signali — kupon bor = ovoz bergan (rasmsizlik
    # eslatmasining 2 xil matni shunga qaraydi, §6.1 a2), (2) dalil.
    coupon: Mapped[str | None] = mapped_column(String(16), nullable=True)
    coupon_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    # TZ v2 5.3 — mijozga "tekshirish jarayonida" matni case boshiga BIR
    # MARTA ketadi. Muhimi: bu yerda YUBORILGAN vaqt saqlanadi, "partiya
    # bor-yo'qligi" emas. Avval "birinchi partiyami?" deb tekshirilardi va
    # birinchi yuborish to'silsa (soya rejimi) yoki xato bersa, keyingi
    # partiyalar ham jim qolib, mijoz matnni HECH QACHON olmasdi.
    followup_sent_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
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


class RelayDirection(str, enum.Enum):
    TO_BOT = "TO_BOT"
    FROM_BOT = "FROM_BOT"


class RelayLog(Base):
    """Har bir tekshiruv-bot bilan almashinuv izi — TZ 11.5 ("relay_log —
    har bir uzatish izi"). Audit J-7 — bu jadval TZ'da aniq talab qilingan
    edi, lekin kodda umuman mavjud emas edi. `coupon_attempts`dan farqli
    (u faqat YAKUNIY natijani saqlaydi), bu HAR bir yo'nalishdagi xabar
    almashinuvni (nomer/kupon yuborilganda va bot javob berganda) qayd
    etadi — natija qanday bo'lishidan qat'i nazar (masalan bot javob
    bermay TIMEOUT bo'lsa ham, yuborilgan so'rov shu yerda qoladi)."""

    __tablename__ = "relay_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"), nullable=True)
    bot_id: Mapped[int | None] = mapped_column(ForeignKey("bots.id"), nullable=True)
    direction: Mapped[RelayDirection] = mapped_column(
        SqlEnum(RelayDirection, native_enum=False, length=16)
    )
    payload: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class OpenBudgetVote(Base):
    """openbudget.uz "Овозларни кўриш" ro'yxatidan olingan bitta ovoz.

    Sayt telefon nomerini MASKALAB beradi (faqat oxirgi 4 raqam ko'rinadi),
    shuning uchun kupon egasini aniqlash ham faqat shu 4 raqam + ovoz vaqti
    bo'yicha mumkin — bu ATOMAR EMAS (bir xil 4 raqamli turli nomerlar
    bo'lishi tabiiy), moslik "dalil" emas, "ishora" sifatida ishlatilishi kerak.

    `raw` — API javobining o'zgarishsiz nusxasi: sayt maydon nomlarini
    o'zgartirsa, eski yozuvlarni qayta talqin qilish imkoni qoladi.
    """

    __tablename__ = "openbudget_votes"
    __table_args__ = (
        # Sayt ovozlarga barqaror ID bermaydi — takrorlanmaslik uchun
        # yagona ishonchli kalit "qaysi tashabbus + maskalangan nomer +
        # ovoz vaqti" uchligi. Shu bilan sinxronizatsiya idempotent bo'ladi
        # (bir xil sahifani qayta o'qish dublikat yaratmaydi).
        UniqueConstraint(
            "initiative_id", "phone_masked", "voted_at_raw", name="uq_openbudget_vote"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    initiative_id: Mapped[str] = mapped_column(String(64), index=True)
    # API qaytargan ko'rinish, masalan "**** **** **12 34" — o'zgarishsiz.
    phone_masked: Mapped[str] = mapped_column(String(64))
    # Undan ajratib olingan oxirgi 4 raqam — qidiruv aynan shu ustun bo'yicha.
    phone_suffix: Mapped[str] = mapped_column(String(4), index=True)
    voted_at_raw: Mapped[str] = mapped_column(String(64))
    # Parse qilib bo'lmasa None — xom qiymat baribir saqlanadi.
    voted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    raw: Mapped[str] = mapped_column(Text, default="")
    fetched_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    """Admin harakatlari tarixi — TZ 11.5, 12.2 (kim, qachon, nima qildi)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_tg_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(64))
    details: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


# =========================================================================== #
# TZ v2 (TZ_v2_Qolda_Admin_Oqimi.md) — qo'lda admin oqimi jadvallari (9.1)
# =========================================================================== #


class SessionStatus(str, enum.Enum):
    """TZ v2 4.3 — har admin akkauntidagi Telethon sessiyasi holati."""

    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    AUTH_LOST = "AUTH_LOST"  # sessiya bekor qilingan — qayta login shart


class AdminSession(Base):
    """Bitta adminning Telethon sessiyasi — TZ v2 4.2 (bitta jarayon, N klient).

    `.session` faylning O'ZI bazada saqlanmaydi (TZ v2 13.4 — u fayl tizimida
    qattiq huquq bilan turadi, backupga ham kirmaydi); bu jadval faqat
    ro'yxat + salomatlik holati.
    """

    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id"), unique=True)
    # sessions/ papkadagi fayl nomi (".session"siz), masalan "admin_3".
    session_name: Mapped[str] = mapped_column(String(255), unique=True)
    phone: Mapped[str] = mapped_column(String(32))
    status: Mapped[SessionStatus] = mapped_column(
        SqlEnum(SessionStatus, native_enum=False, length=16),
        default=SessionStatus.DISCONNECTED,
    )
    last_seen_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class BatchOutcome(str, enum.Enum):
    """TZ v2 9.1 — rasm partiyasining yakuniy natijasi (guruhdagi reaksiya)."""

    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"  # javob tanilmadi (⚠️)
    STALLED = "STALLED"  # tekshiruvchi javob bermadi (⏳)


class OutcomeSource(str, enum.Enum):
    """Natija qayerdan kelgani: tizim avtomatik qo'ydimi yoki odam qo'lda
    reaksiyani o'zgartirdimi (TZ v2 7.3 — override statistikada alohida)."""

    AUTO = "AUTO"
    MANUAL = "MANUAL"


class ScreenshotBatch(Base):
    """Admin mijozga tashlagan 1-3 rasmlik partiya — TZ v2 5-bo'lim."""

    __tablename__ = "screenshot_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"))
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id"))
    phone: Mapped[str] = mapped_column(String(32))
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    # Telethon media identifikatorlari JSON ro'yxat sifatida — forward
    # qayta yuklamasdan ishlashi uchun (TZ v2 5.2).
    file_ids: Mapped[str] = mapped_column(Text, default="[]")
    group_chat_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    group_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # TZ v2 5.4 — bitta nomerga ikkinchi partiya (dublikat) belgisi:
    # statistikada ikki marta hisoblanmaydi, superadminga alert ketadi.
    is_duplicate: Mapped[bool] = mapped_column(default=False)
    duplicate_of_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("screenshot_batches.id"), nullable=True
    )
    sent_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    outcome: Mapped[BatchOutcome] = mapped_column(
        SqlEnum(BatchOutcome, native_enum=False, length=16), default=BatchOutcome.PENDING
    )
    outcome_source: Mapped[OutcomeSource] = mapped_column(
        SqlEnum(OutcomeSource, native_enum=False, length=16), default=OutcomeSource.AUTO
    )
    # Odam guruhda reaksiyani qo'lda o'zgartirgan bo'lsa — kim va qachon.
    reacted_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reacted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)


class CheckTrigger(str, enum.Enum):
    """TZ v2 6.1 — tekshiruv qanday boshlangani."""

    MANUAL = "MANUAL"  # admin /check bilan
    AUTO = "AUTO"  # 1.5 soatlik taymer


class CheckResult(str, enum.Enum):
    """TZ v2 9.1 — tekshiruvchi lichka javobining tanilgan natijasi."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    UNRECOGNIZED = "UNRECOGNIZED"  # shablonlarga mos kelmadi -> NEEDS_ADMIN
    NO_REPLY = "NO_REPLY"  # stall muddati o'tdi (so'rov hamon ochiq)


class NotifiedBy(str, enum.Enum):
    """TZ v2 7.1 — natija mijozga qanday yetkazilgani (aralash rejim)."""

    AUTO = "AUTO"  # PASSED — tizim avtomatik yozdi
    ADMIN = "ADMIN"  # FAILED — admin tugma bosib tasdiqladi


class CheckRequest(Base):
    """Tekshiruvchi lichkaga yuborilgan bitta so'rov — TZ v2 6-bo'lim."""

    __tablename__ = "check_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"))
    phone: Mapped[str] = mapped_column(String(32))
    # So'rov qaysi adminning akkauntidan ketadi (statistika ham shundan).
    requested_by_admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id"))
    trigger: Mapped[CheckTrigger] = mapped_column(
        SqlEnum(CheckTrigger, native_enum=False, length=16)
    )
    # TZ v2 6.1 a4 — FAILED'dan keyin admin /check bilan qayta tekshirsa.
    is_recheck: Mapped[bool] = mapped_column(default=False)
    queued_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    sent_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    # Tekshiruvchiga yuborilgan xabarimizning Telegram id'si — tekshiruvchi
    # REPLY qilib javob bersa, so'rovga aniq bog'lash uchun (TZ v2 6.4.5,
    # 1-ustuvorlik).
    sent_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    replied_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    result: Mapped[CheckResult | None] = mapped_column(
        SqlEnum(CheckResult, native_enum=False, length=16), nullable=True
    )
    raw_reply: Mapped[str] = mapped_column(Text, default="")
    # TZ v2 6.5 (kech javob) — case yopilgandan keyin kelgan javob natijani
    # avtomatik to'g'irlagan bo'lsa (statistikada alohida ko'rinadi).
    late_corrected: Mapped[bool] = mapped_column(default=False)
    customer_notified_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    notified_by: Mapped[NotifiedBy | None] = mapped_column(
        SqlEnum(NotifiedBy, native_enum=False, length=16), nullable=True
    )


class JobKind(str, enum.Enum):
    """TZ v2 9.1/9.4 — bazada saqlanadigan rejalashtirilgan ish turlari.

    Taymerlar XOTIRADA EMAS (v1 `_customer_timers`dan farqli) — 1.5 soatlik
    kutishlar restart'dan omon qolishi shart.
    """

    CHECK_DUE = "CHECK_DUE"  # rasm vaqti + 90daq -> tekshiruvni boshlash
    REMIND_NO_SCREENSHOT = "REMIND_NO_SCREENSHOT"  # rasm tashlanmagan eslatmasi
    STALLED_ALERT = "STALLED_ALERT"  # tekshiruvchi javobsiz — superadmin alert
    DAILY_REPORT = "DAILY_REPORT"  # 21:00 kunlik hisobot
    # TZ v2 7.1 — FAILED natijani admin adminbotda tasdiqladi: mijozga
    # yuborishni Teleton bajaradi (adminbot Telethon'ga ega emas — bayroq
    # naqshi, faqat endi scheduled_jobs orqali).
    NOTIFY_FAILED = "NOTIFY_FAILED"


class ScheduledJob(Base):
    """Muddati kelganda poller bajaradigan ish — TZ v2 9.4."""

    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[JobKind] = mapped_column(SqlEnum(JobKind, native_enum=False, length=32))
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"), nullable=True)
    due_at: Mapped[datetime.datetime] = mapped_column(DateTime, index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    done_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
