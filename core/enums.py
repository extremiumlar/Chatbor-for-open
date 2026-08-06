"""Case statuslar — TZ 6-bo'lim. Bu ro'yxatdan tashqari status qo'shilmaydi."""

import enum


class CaseStatus(str, enum.Enum):
    NUMBER_RECEIVED = "NUMBER_RECEIVED"
    SENT_TO_BOT = "SENT_TO_BOT"
    AWAITING_COUPON = "AWAITING_COUPON"
    COUPON_SENT_TO_BOT = "COUPON_SENT_TO_BOT"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    SUSPICIOUS_HOLD = "SUSPICIOUS_HOLD"
    NEEDS_ADMIN = "NEEDS_ADMIN"
    TIMEOUT = "TIMEOUT"
    CUSTOMER_TIMEOUT = "CUSTOMER_TIMEOUT"
    EXPIRED_SESSION = "EXPIRED_SESSION"
    DUPLICATE_ACTIVE = "DUPLICATE_ACTIVE"
    ALREADY_CONFIRMED = "ALREADY_CONFIRMED"


# Case bu holatlardan birida bo'lsa "faol" (bot bilan jarayon davom etmoqda)
# hisoblanadi — TZ 2.3 (Q49) shu ro'yxatga qarab "faol case bormi" tekshiradi:
# shu holatlardan birida boshqa/o'sha nomer kelsa DUPLICATE_ACTIVE bo'ladi.
ACTIVE_STATUSES = frozenset(
    {
        CaseStatus.NUMBER_RECEIVED,
        CaseStatus.SENT_TO_BOT,
        CaseStatus.AWAITING_COUPON,
        CaseStatus.COUPON_SENT_TO_BOT,
    }
)

# MVP-3: EXPIRED/NEEDS_ADMIN/SUSPICIOUS_HOLD bot bilan "band" emas (bot allaqachon
# bo'shagan), lekin case hamon "hal bo'lmagan" — mijoz FARQLI nomer yuborsa bu
# ham DUPLICATE_ACTIVE kabi ishlov olishi kerak (case_manager.PENDING_STATUSES
# javob so'ralgan, lekin foydalanuvchi tomonidan taqdim etilmagan taxmin —
# TZ aniq javob bermagan, shuning uchun eng xavfsiz variant: yangi case ochish
# o'rniga avval aniqlashtirish/admin xabardor qilish). EXPIRED + AYNAN O'SHA
# nomer kelsa esa alohida — qayta-urinish sikli (2.1), PENDING_STATUSES'ga
# kirmaydi, chunki case_manager buni ACTIVE/PENDING tekshiruvidan OLDIN
# alohida ushlaydi.
PENDING_STATUSES = ACTIVE_STATUSES | frozenset(
    {CaseStatus.EXPIRED, CaseStatus.NEEDS_ADMIN, CaseStatus.SUSPICIOUS_HOLD}
)

# Audit K-1 tuzatishi — case_manager.handle_phone_detected'ning "bu case hali
# hal bo'lmagan, avtomatik dispatch qilinmasin" tekshiruvi shu ro'yxatga
# qaraydi. Oldin faqat (NEEDS_ADMIN, SUSPICIOUS_HOLD) tekshirilardi — TIMEOUT
# va DUPLICATE_ACTIVE holatlari tushib qolgani uchun ular bo'yicha kelgan
# takroriy xabar "yangi murojaat" deb noto'g'ri qabul qilinardi (K-1).
HELD_STATUSES = frozenset(
    {
        CaseStatus.NEEDS_ADMIN,
        CaseStatus.SUSPICIOUS_HOLD,
        CaseStatus.TIMEOUT,
        CaseStatus.DUPLICATE_ACTIVE,
    }
)

# Audit K-3 tuzatishi — admin qo'lda Tasdiqlash/Rad/Qayta-uzatish qila
# oladigan holatlar (TZ 9.3). kb.case_card (tugma ko'rsatish) va
# core.logic.case_admin (server tomoni tekshiruvi) ikkovi ham shu bitta
# ro'yxatdan foydalanadi — ikkalasi mos kelmay qolmasligi uchun.
MANUAL_RESOLVABLE_STATUSES = frozenset(
    {
        CaseStatus.NEEDS_ADMIN,
        CaseStatus.TIMEOUT,
        CaseStatus.DUPLICATE_ACTIVE,
        CaseStatus.EXPIRED,
        CaseStatus.CUSTOMER_TIMEOUT,
    }
)

# Audit O-2 — "muammoli holatlar" (TZ 10-bo'lim). Avval adminbot_service/bot.py
# (⚠️ Muammolar ro'yxati) va core/logic/stats.py (📊 Statistikadagi
# "muammoli holatlar soni") har biri O'Z, bir-biriga mos kelmaydigan
# nusxasini tutardi — adminbot TIMEOUT'ni ham qamrab olardi, stats esa
# yo'q, shuning uchun ikki ekrandagi son hech qachon to'g'ri kelmasdi.
# Bu ro'yxat ma'no jihatidan HELD_STATUSES bilan bir xil (case admin
# e'tiborini kutmoqda) — shuning uchun uni alias qilamiz, ikkita alohida
# qo'lda yozilgan ro'yxat o'rniga.
PROBLEM_STATUSES = HELD_STATUSES
