"""Rol asosidagi ruxsatlar — TZ 14-bo'lim (Q25, Q43).

Bu modul — **yagona haqiqat manbai**. Buyruq qaysi rolga ochiqligi faqat shu
yerda yoziladi; Adminbot ham ko'rsatishda (menyu/yordam), ham bajarishda
(tekshiruv) aynan shu jadvalga qaraydi. Ikki joyda alohida ro'yxat saqlansa,
ertami-kech ular bir-biridan chetlashadi va "ko'rinmaydi, lekin ishlayveradi"
degan teshik paydo bo'ladi.

TZ 14 bo'linishi:
    Owner       — hammasi
    Rop         — statistika, adminlar nazorati, hisobotlar
    Dasturchi   — texnik sozlash, botlar, shablonlar
    Admin       — o'z lichkasi, o'z case'lari (operator)
    Kuzatuvchi  — faqat ko'rish

MUHIM: tugmani yashirish — himoya EMAS. Telegram'da eski xabardagi tugmani
qayta bosish yoki callback_data'ni qo'lda yuborish mumkin, shuning uchun
ruxsat SERVER TOMONIDA ham tekshiriladi (`adminbot_service.bot`dagi
`RolePermission` middleware).
"""

from dataclasses import dataclass

from core.models import Admin, AdminRole

OWNER = AdminRole.OWNER
ROP = AdminRole.ROP
DASTURCHI = AdminRole.DASTURCHI
ADMIN = AdminRole.ADMIN
KUZATUVCHI = AdminRole.KUZATUVCHI

ALL_ROLES = frozenset(AdminRole)

# Faqat ko'rish (hech narsa o'zgartirmaydi) — hamma rol uchun ochiq.
_VIEW = ALL_ROLES

# Operator ishi: murojaatlarni yuritish. Kuzatuvchi ko'ra oladi, lekin
# o'zgartira olmaydi — shuning uchun u bu ro'yxatda yo'q.
_OPERATE = frozenset({OWNER, ROP, DASTURCHI, ADMIN})

# Texnik sozlash: botlar, shablonlar, tanish naqshlari (TZ 14 "Dasturchi").
_TECH = frozenset({OWNER, DASTURCHI})

# Boshqaruv: statistika sozlamalari, hisobotlar, bildirishnoma rejimi.
_MANAGE = frozenset({OWNER, ROP})

# Faqat egasi: rol berish, adminni o'chirish/yoqish.
_OWNER_ONLY = frozenset({OWNER})

# Tashxis (diagnostika): o'zi hech narsani buzmaydigan, lekin "nima bo'lyapti?"
# savoliga javob beradigan bo'limlar — adminlar ro'yxati, harakatlar tarixi,
# bildirishnoma tafsiloti. Dasturchi ularsiz nosozlikni topa olmaydi: kim
# nimani o'zgartirgani ko'rinmasa, texnik sozlashning o'zi ham ko'r ish
# bo'lib qoladi. Shuning uchun Boshqaruv + Texnik birga.
_MANAGE_OR_TECH = _MANAGE | _TECH


@dataclass(frozen=True)
class Perm:
    """Bitta buyruq/tugma haqida hamma narsa — ruxsat + ko'rsatish matni."""

    key: str
    roles: frozenset
    section: str
    label: str
    hint: str = ""


SECTION_ORDER = [
    "Ko'rish va qidiruv",
    "Murojaatlar bilan ishlash",
    "Texnik sozlash",
    "Boshqaruv va hisobot",
    "Adminlar",
]


def _p(key, roles, section, label, hint=""):
    return Perm(key=key, roles=roles, section=section, label=label, hint=hint)


# --------------------------------------------------------------------------- #
# BUYRUQLAR
# --------------------------------------------------------------------------- #

COMMANDS: dict[str, Perm] = {
    p.key: p
    for p in [
        # --- Ko'rish (hamma, jumladan Kuzatuvchi) ---
        _p("help", _VIEW, "Ko'rish va qidiruv", "/help", "O'zingizga ochiq buyruqlar ro'yxati"),
        _p("myrole", _VIEW, "Ko'rish va qidiruv", "/myrole", "Qaysi rolda ekaningiz"),
        _p("stats", _VIEW, "Ko'rish va qidiruv", "/stats", "Umumiy statistika"),
        _p("vstats", _VIEW, "Ko'rish va qidiruv", "/vstats", "v2 statistika (Bugun/Hafta/Oy)"),
        _p("pending", _VIEW, "Ko'rish va qidiruv", "/pending", "Navbatdagi murojaatlar"),
        _p("problems", _VIEW, "Ko'rish va qidiruv", "/problems", "E'tibor talab qiladiganlar"),
        _p("bots", _VIEW, "Ko'rish va qidiruv", "/bots", "Tekshiruv botlari holati"),
        _p("templates", _VIEW, "Ko'rish va qidiruv", "/templates", "Mijoz shablonlarini ko'rish"),
        _p("botpatterns", _VIEW, "Ko'rish va qidiruv", "/botpatterns", "Bot-tanish shablonlari"),
        _p("checkpatterns", _VIEW, "Ko'rish va qidiruv", "/checkpatterns", "Javob tanish shablonlari"),
        # --- Murojaatlar bilan ishlash (operator ishi) ---
        _p("unrecognized", _OPERATE, "Murojaatlar bilan ishlash", "/unrecognized",
           "Tanilmagan javoblar jurnali"),
        _p("testcheck", _OPERATE, "Murojaatlar bilan ishlash", "/testcheck &lt;matn&gt;",
           "Javob qanday tanilishini sinash"),
        # --- Texnik sozlash (Dasturchi) ---
        _p("addbot", _TECH, "Texnik sozlash", "/addbot &lt;username&gt;", "Yangi tekshiruv bot"),
        _p("settemplate", _TECH, "Texnik sozlash", "/settemplate &lt;KEY&gt; &lt;matn&gt;",
           "Mijoz shablonini o'zgartirish"),
        _p("setbotpattern", _TECH, "Texnik sozlash", "/setbotpattern &lt;KEY&gt; &lt;matn&gt;",
           "Bot-tanish shablonini o'zgartirish"),
        _p("addcheckpattern", _TECH, "Texnik sozlash", "/addcheckpattern", "Tanish naqshi qo'shish"),
        _p("delcheckpattern", _TECH, "Texnik sozlash", "/delcheckpattern", "Tanish naqshini o'chirish"),
        _p("setchecker", _TECH, "Texnik sozlash", "/setchecker", "Tekshiruvchi lichkani belgilash"),
        _p("setgroup", _TECH, "Texnik sozlash", "/setgroup", "Nazorat guruhini belgilash"),
        # TZ v2 4.3 — sessiya holati. Rop uchun ham ochiq: sessiya o'lsa
        # o'sha adminning mijozlari yo'qoladi, bu boshqaruv savoli hamdir.
        _p("sessions", _MANAGE | _TECH, "Texnik sozlash", "/sessions",
           "Admin akkauntlari sessiya holati"),
        _p("shadow", _TECH, "Texnik sozlash", "/shadow", "Soya rejimi (mijozga yozilmaydi)"),
        _p("uyqu", _TECH, "Texnik sozlash", "/uyqu off|on", "Kompyuter uyqu rejimi"),
        # --- Boshqaruv va hisobot (Rop) ---
        # Bildirishnoma tafsiloti — nosozlik qidirayotgan Dasturchiga ham
        # kerak (batafsil rejimda har hodisa alert bo'lib chiqadi).
        _p("notify", _MANAGE_OR_TECH, "Boshqaruv va hisobot", "/notify",
           "Bildirishnoma rejimi"),
        # Kunlik hisobot vaqti — sof boshqaruv qarori, texnik ish emas.
        _p("setreporttime", _MANAGE, "Boshqaruv va hisobot", "/setreporttime HH:MM",
           "Kunlik hisobot vaqti"),
        _p("audit", _MANAGE_OR_TECH, "Boshqaruv va hisobot", "/audit",
           "Admin harakatlari tarixi"),
        # --- Adminlar ---
        # Ro'yxatning O'ZI ko'rish amali (kim qaysi rolda, tg_id nechchi) —
        # Dasturchiga sozlash uchun kerak. O'ZGARTIRISH (pastdagi ikkitasi)
        # esa faqat egasida qoladi.
        _p("admins", _MANAGE_OR_TECH, "Adminlar", "/admins", "Adminlar ro'yxati"),
        _p("setrole", _OWNER_ONLY, "Adminlar", "/setrole", "Rol berish"),
        _p("setactive", _OWNER_ONLY, "Adminlar", "/setactive", "Adminni yoqish/o'chirish"),
    ]
}


# --------------------------------------------------------------------------- #
# TUGMALAR (callback_data prefikslari va menyu tugmalari)
# --------------------------------------------------------------------------- #
#
# Tugma bosilishi ham buyruq bilan bir xil kuchga ega — shuning uchun ular ham
# shu yerda ro'yxatdan o'tadi. Prefiks = `callback_data`ning birinchi bo'lagi
# (masalan `bot:12:off` -> `bot`), lekin o'zgartiruvchi amallar uchun ikkinchi
# bo'lak ham hisobga olinadi (pastdagi `callback_key`ga qarang).

CALLBACKS: dict[str, frozenset] = {
    # Navigatsiya va ko'rish
    "nav": _VIEW,
    "pg": _VIEW,
    "noop": _VIEW,
    "cancel": _VIEW,
    # Statistika — hamma ko'ra oladi; "kim nimani ko'radi" cheklovi
    # ko'rsatish qatlamida (`_build_vstats`: oddiy admin faqat o'zinikini
    # oladi, qaysi tugmani bosishidan qat'i nazar).
    "vst": _VIEW,
    "tpl:view": _VIEW,
    "bot:view": _VIEW,
    "cs:view": _VIEW,
    "usr:view": _VIEW,
    # TZ v2 4.3 — "🔌 Sessiyalar" tugmasi `/sessions` bilan bir xil ruxsatda.
    "nav:sessions": _MANAGE | _TECH,
    # Murojaat ustida amal (operator)
    "cs:act": _OPERATE,
    "usr:act": _OPERATE,
    "safe": _OPERATE,
    "block": _OPERATE,
    # v2: FAILED natijani tasdiqlash (mijozga yuborish/bekor) — operator ishi.
    "vres": _OPERATE,
    # v2: tanilmagan javobni shablonga aylantirish.
    # MUHIM: bu tugma `/addcheckpattern` bilan AYNAN bir xil ishni bajaradi —
    # tanish shabloniga yozadi. Shuning uchun ruxsati ham bir xil (`_TECH`)
    # bo'lishi shart. Avval tugma `_MANAGE` edi: Dasturchi buyruq bilan
    # shablon qo'sha olardi, lekin tugmani bossa rad etilardi; Rop esa
    # aksincha. Bir amalning ikki yo'li ikki xil rolga ochiq edi.
    "ucp": _TECH,
    # Texnik o'zgartirish
    "tpl:edit": _TECH,
    "bot:act": _TECH,
    "newbot": _TECH,
    # Boshqaruv (buyruq bilan bir xil — `/notify` ga qarang)
    "notify": _MANAGE_OR_TECH,
}

MENU_BUTTONS: dict[str, frozenset] = {
    "📊 Statistika": _VIEW,
    "⚠️ Muammolar": _VIEW,
    "🤖 Botlar": _VIEW,
    "⏳ Navbat": _VIEW,
    "🔍 Nomer qidirish": _VIEW,
    "ℹ️ Yordam": _VIEW,
    "📝 Shablonlar": _VIEW,
    "⚙️ Sozlamalar": _MANAGE | _TECH,
}


# --------------------------------------------------------------------------- #
# Tekshirish yordamchilari
# --------------------------------------------------------------------------- #


def callback_key(data: str) -> str:
    """`callback_data`dan ruxsat kalitini ajratadi.

    Bir prefiksning ichida ham ko'rish, ham o'zgartirish bo'lishi mumkin
    (masalan `cs:5` — kartochkani ko'rish, `cs:5:ok` — qo'lda tasdiqlash).
    Shuning uchun kalit "ko'rish" va "amal"ga bo'linadi.
    """
    parts = data.split(":")
    head = parts[0]

    # Navigatsiya odatda hamma uchun ochiq ("nav" kaliti), lekin ayrim
    # bo'limlar buyruq bilan bir xil darajada yopiq bo'lishi kerak. Shunday
    # bo'lim `CALLBACKS`ga TO'LIQ nomi bilan yoziladi (masalan
    # "nav:sessions") va o'shanda umumiy "nav" o'rniga aynan o'sha yozuv
    # ishlaydi — tugma bilan buyruq bir xil ruxsatga bo'ysunadi.
    if head == "nav" and data in CALLBACKS:
        return data

    if head in ("nav", "pg", "noop", "cancel", "safe", "block", "notify", "newbot"):
        return head

    if head in ("cs", "usr", "bot", "tpl"):
        # 2 bo'lak = ko'rish (`cs:5`), 3+ bo'lak = amal (`cs:5:ok`).
        # `tpl` istisno: `tpl:c:KEY` — ko'rish, `tpl:c:KEY:edit` — tahrir.
        if head == "tpl":
            return "tpl:edit" if data.endswith(":edit") else "tpl:view"
        if head == "bot":
            return "bot:view" if len(parts) == 2 else "bot:act"
        return f"{head}:view" if len(parts) == 2 else f"{head}:act"

    return head


def roles_for_callback(data: str) -> frozenset:
    return CALLBACKS.get(callback_key(data), _OWNER_ONLY)


def can_use_command(admin: Admin, command: str) -> bool:
    perm = COMMANDS.get(command)
    if perm is None:
        # Ro'yxatda yo'q buyruq — ataylab eng qattiq holat (faqat Owner).
        # Yangi buyruq qo'shilib, matritsaga yozilmay qolsa, u jimgina
        # hammaga ochiq bo'lib qolmasligi kerak.
        return admin.role == OWNER
    return admin.role in perm.roles


def can_use_callback(admin: Admin, data: str) -> bool:
    return admin.role in roles_for_callback(data)


def can_use_menu_button(admin: Admin, text: str) -> bool:
    roles = MENU_BUTTONS.get(text)
    return True if roles is None else admin.role in roles


def allowed_commands(admin: Admin) -> list[Perm]:
    return [p for p in COMMANDS.values() if admin.role in p.roles]


def role_label(role: AdminRole) -> str:
    return {
        OWNER: "👑 Owner (egasi) — hamma huquq",
        ROP: "📊 Rop (boshliq) — statistika, hisobot, adminlar nazorati",
        DASTURCHI: "🛠 Dasturchi — texnik sozlash, botlar, shablonlar",
        ADMIN: "👤 Admin (operator) — murojaatlar bilan ishlash",
        KUZATUVCHI: "👁 Kuzatuvchi — faqat ko'rish",
    }[role]


def denial_message(admin: Admin, what: str) -> str:
    """Ruxsat yo'q bo'lganda ko'rsatiladigan aniq xabar."""
    return (
        f"⛔ Bu amal sizning rolingizga ochiq emas.\n\n"
        f"Siz: {role_label(admin.role)}\n"
        f"So'ralgan: <code>{what}</code>\n\n"
        f"O'zingizga ochiq buyruqlarni ko'rish uchun /help yuboring."
    )
