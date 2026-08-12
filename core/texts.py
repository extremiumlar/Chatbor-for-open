"""Mijozga yuboriladigan shablonlar — TZ 7.2.

Bular Adminbot orqali sozlanadigan matnlar (MVP-2, TZ 9.2 `/templates`).
MVP-1 da hali Adminbot yo'q, shuning uchun boshlang'ich qiymatlar shu yerda
konstanta sifatida turadi (hardcode emas — alohida faylda, TZ 3-bo'lim
"Til" qatoriga mos), keyinchalik bazaga ko'chiriladi.
"""

COUPON_REQUEST = "Iltimos, kupon raqamingizni yuboring."
CONFIRMED = "Tabriklaymiz! Sizning kuponingiz tasdiqlandi."
REJECTED = "Afsuski, kuponingiz rad etildi."
EXPIRED_RETRY = (
    "Kuponingiz muddati o'tdi. Qaytadan urinib ko'rish uchun "
    "nomeringizni qaytadan yuboring."
)
IMAGE_INSTEAD_OF_TEXT = "Rasm ko'rinishida emas, kod ko'rinishida yuboring."
DUPLICATE_ACTIVE = (
    "Sizning oldingi so'rovingiz hali yakunlanmagan. Avvalgi jarayonni "
    "davom ettiramizmi yoki yangi nomer bilan boshlaymizmi?"
)
ALREADY_CONFIRMED = "Bu nomer allaqachon tasdiqlangan."
# TZ 2.1 (Q58) — qayta yuborilgan kupon avvalgisi bilan bir xil bo'lsa
DUPLICATE_COUPON = "Bu eskisi bilan bir xil kupon. Boshqa kupon raqamini yuboring."

# TZ v2 5.3 — admin rasm tashlagach mijozga avtomatik tushadigan matn.
SCREENSHOT_FOLLOWUP = (
    "Kuponingiz tekshirish jarayonida. Iltimos, 1.5 soatdan keyin eslating."
)

# TZ v2 7.2 — tekshiruv natijasi mijozga (aralash rejim, §7.1).
RESULT_PASSED = "Tabriklaymiz! Ovozingiz muvaffaqiyatli qabul qilingan. ✅"
RESULT_FAILED = (
    "Afsuski, ovozingiz tizimda ko'rinmadi. Iltimos, qaytadan urinib "
    "ko'ring yoki menga yozing."
)
