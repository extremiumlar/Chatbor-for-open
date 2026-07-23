"""
Data Relay Userbot (Telethon, asyncio)
======================================

Vazifasi:
    - Foydalanuvchi shaxsiy akkauntga (lichkaga) telefon raqamini yuboradi.
    - Keyin bot bergan kupon/chipta ID-sini yuboradi.
    - Skript har ikkala ma'lumotni ham o'z boshqaruv botingizga (RELAY_TARGET)
      uzatadi — foydalanuvchi seansini (state) yo'qotmagan holda.

Muhim:
    - Bu tizim TASHQI xizmat kodlarini (Telegram login, SMS OTP, bank kodi)
      yig'ish uchun EMAS. U faqat sizning o'z botingiz generatsiya qilgan
      ichki kupon/aksiya ID-larini uzatadi.

O'rnatish:
    pip install telethon
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum, auto

from telethon import TelegramClient, events

# --------------------------------------------------------------------------- #
# 1. KONFIGURATSIYA
# --------------------------------------------------------------------------- #
# api_id / api_hash ni https://my.telegram.org saytidan oling.
API_ID = 1234567
API_HASH = "your_api_hash_here"

# Userbot ishlaydigan seans nomi (fayl nomi sifatida saqlanadi).
SESSION_NAME = "relay_userbot"

# Ma'lumot uzatiladigan manzil: o'z botingizning @username yoki numeric ID.
# Masalan: "@MyCustomBot"  yoki  123456789
RELAY_TARGET = "@MyCustomBot"

# Foydalanuvchi seansi necha soniyadan keyin "eskirgan" hisoblanadi (TTL).
SESSION_TTL_SECONDS = 300          # 5 daqiqa
# Background tozalovchi necha soniyada bir tekshiradi.
CLEANUP_INTERVAL_SECONDS = 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
log = logging.getLogger("relay")


# --------------------------------------------------------------------------- #
# 2. STATE (holat) MODELI
# --------------------------------------------------------------------------- #
class Step(Enum):
    """Foydalanuvchi jarayonning qaysi bosqichida turganini bildiradi."""
    AWAITING_PHONE = auto()     # Telefon raqami kutilmoqda
    AWAITING_COUPON = auto()    # Kupon/chipta ID-si kutilmoqda
    DONE = auto()               # Yakunlandi


@dataclass
class UserSession:
    """Bitta foydalanuvchining vaqtinchalik holati."""
    user_id: int
    step: Step = Step.AWAITING_PHONE
    phone: str | None = None
    coupon: str | None = None
    updated_at: float = field(default_factory=time.monotonic)
    # Har bir foydalanuvchi uchun alohida qulf — bir vaqtda kelgan
    # xabarlar ketma-ket, tartib bilan qayta ishlanishini kafolatlaydi.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def touch(self) -> None:
        """Har faoliyatdan keyin TTL taymerini yangilaydi."""
        self.updated_at = time.monotonic()

    def is_expired(self, ttl: float) -> bool:
        return (time.monotonic() - self.updated_at) > ttl


class SessionStore:
    """
    Barcha foydalanuvchi seanslarini user_id bo'yicha saqlaydigan
    markaziy xotira. Bir nechta foydalanuvchi bir vaqtda yozganda
    ma'lumotlar chalkashmasligini ta'minlaydi.
    """
    def __init__(self) -> None:
        self._sessions: dict[int, UserSession] = {}
        # dict-ning o'ziga yozish/o'chirishni himoya qiluvchi global qulf.
        self._guard = asyncio.Lock()

    async def get_or_create(self, user_id: int) -> UserSession:
        async with self._guard:
            session = self._sessions.get(user_id)
            if session is None:
                session = UserSession(user_id=user_id)
                self._sessions[user_id] = session
                log.info("Yangi seans yaratildi: user_id=%s", user_id)
            return session

    async def remove(self, user_id: int) -> None:
        async with self._guard:
            self._sessions.pop(user_id, None)

    async def sweep_expired(self, ttl: float) -> int:
        """Eskirgan seanslarni o'chiradi, o'chirilganlar sonini qaytaradi."""
        async with self._guard:
            expired = [
                uid for uid, s in self._sessions.items() if s.is_expired(ttl)
            ]
            for uid in expired:
                del self._sessions[uid]
            if expired:
                log.info("TTL tozalash: %d ta eskirgan seans o'chirildi", len(expired))
            return len(expired)


# --------------------------------------------------------------------------- #
# 3. YORDAMCHI FUNKSIYALAR (validatsiya)
# --------------------------------------------------------------------------- #
PHONE_RE = re.compile(r"^\+?\d[\d\s\-()]{7,15}\d$")
COUPON_RE = re.compile(r"^\d{4,12}$")   # o'z formatingizga moslang


def looks_like_phone(text: str) -> bool:
    return bool(PHONE_RE.match(text.strip()))


def looks_like_coupon(text: str) -> bool:
    return bool(COUPON_RE.match(text.strip()))


# --------------------------------------------------------------------------- #
# 4. ASOSIY KLIENT VA HODISALAR
# --------------------------------------------------------------------------- #
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
store = SessionStore()


async def relay_to_bot(text: str) -> None:
    """Yig'ilgan ma'lumotni boshqaruv botingizga matn sifatida yuboradi."""
    await client.send_message(RELAY_TARGET, text)


@client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def handle_private_message(event: events.NewMessage.Event) -> None:
    """
    Lichkaga kelgan har bir shaxsiy xabarni qayta ishlaydi.
    Botlardan yoki o'zimizdan kelgan xabarlarni e'tiborsiz qoldiradi.
    """
    sender = await event.get_sender()
    # Bot yoki o'zimiz yozgan xabarlarni tashlab ketamiz.
    if sender is None or getattr(sender, "bot", False) or event.out:
        return

    user_id = event.sender_id
    text = (event.raw_text or "").strip()
    if not text:
        return

    session = await store.get_or_create(user_id)

    # Aynan shu foydalanuvchining xabarlarini ketma-ket qayta ishlaymiz.
    async with session.lock:
        session.touch()

        # --- 1-BOSQICH: telefon raqami ----------------------------------- #
        if session.step is Step.AWAITING_PHONE:
            if not looks_like_phone(text):
                await event.reply(
                    "Iltimos, avval telefon raqamingizni yuboring "
                    "(masalan: +998901234567)."
                )
                return

            session.phone = text
            session.step = Step.AWAITING_COUPON

            await relay_to_bot(f"📞 Yangi telefon raqami:\nuser_id: {user_id}\nphone: {text}")
            await event.reply(
                "Rahmat! Endi botdan olgan kupon/chipta raqamingizni yuboring."
            )
            log.info("user_id=%s telefon qabul qilindi", user_id)
            return

        # --- 2-BOSQICH: kupon ID -------------------------------------- #
        if session.step is Step.AWAITING_COUPON:
            if not looks_like_coupon(text):
                await event.reply(
                    "Kupon raqami noto'g'ri formatda. Faqat raqamlardan iborat "
                    "kupon ID-sini yuboring."
                )
                return

            session.coupon = text
            session.step = Step.DONE

            await relay_to_bot(
                "🎟 Kupon tasdiqlash:\n"
                f"user_id: {user_id}\n"
                f"phone: {session.phone}\n"
                f"coupon: {text}"
            )
            await event.reply("✅ Ma'lumotlaringiz qabul qilindi va tekshirishga yuborildi!")
            log.info("user_id=%s kupon qabul qilindi, seans yakunlandi", user_id)

            # Yakunlangan seansni darhol tozalaymiz.
            await store.remove(user_id)
            return

        # --- Yakunlangandan keyin qayta yozilsa --------------------------- #
        await event.reply(
            "Sizning oldingi so'rovingiz allaqachon qabul qilingan. "
            "Yangi kupon uchun telefon raqamingizdan boshlang."
        )


# --------------------------------------------------------------------------- #
# 5. BACKGROUND TTL TOZALOVCHI
# --------------------------------------------------------------------------- #
async def cleanup_worker() -> None:
    """Muntazam ravishda eskirgan (yarim tashlab ketilgan) seanslarni o'chiradi."""
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            await store.sweep_expired(SESSION_TTL_SECONDS)
        except Exception:  # tozalash xatosi butun botni to'xtatmasligi kerak
            log.exception("Tozalash jarayonida xatolik")


# --------------------------------------------------------------------------- #
# 6. ISHGA TUSHIRISH
# --------------------------------------------------------------------------- #
async def main() -> None:
    await client.start()   # birinchi ishga tushirishda telefon/kod so'raydi
    me = await client.get_me()
    log.info("Userbot ishga tushdi: %s (id=%s)", me.first_name, me.id)

    # TTL tozalovchini fon rejimida ishga tushiramiz.
    cleanup_task = asyncio.create_task(cleanup_worker())

    try:
        await client.run_until_disconnected()
    finally:
        cleanup_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
