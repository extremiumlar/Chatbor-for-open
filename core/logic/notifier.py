"""Adminbotga bildirishnoma yuborish — TZ 9.1, 5.1, 5.2.

Teleton va Adminbot alohida jarayon bo'lgani uchun (TZ 13.1), Teleton
tomonidan yig'ilgan alertlar to'g'ridan-to'g'ri Adminbot tokeni orqali
yuboriladi (o'z aiogram.Bot nusxasi bilan) — alohida navbat/broker shart
emas, chunki xabar yuborish faqat token + chat_id talab qiladi. Inline
tugmalar (masalan "Xavfsiz"/"Bloklash") shu bot tokeniga tegishli bo'lgani
uchun, ularning callback'ini adminbot_service'dagi Dispatcher (boshqa
jarayon, lekin bir xil token) qabul qiladi — Telegram callback'larni
token bo'yicha marshrutlaydi, qaysi client obyekti xabarni yuborganiga
bog'liq emas.
"""

import logging
from typing import Callable

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core.logic.admins import list_admin_tg_ids
from core.logic.settings_store import is_verbose

log = logging.getLogger("notifier")


def _open_chat_button(tg_user_id: int, tg_username: str | None) -> InlineKeyboardButton:
    url = f"https://t.me/{tg_username}" if tg_username else f"tg://user?id={tg_user_id}"
    return InlineKeyboardButton(text="Lichkaga o'tish", url=url)


class AdminNotifier:
    def __init__(self, session_factory: Callable, bot_token: str) -> None:
        self.session_factory = session_factory
        self._bot = Bot(token=bot_token) if bot_token else None
        if self._bot is None:
            log.warning(
                "ADMINBOT_TOKEN sozlanmagan — admin bildirishnomalari faqat log'ga yoziladi."
            )

    async def send(self, message: str, important: bool = True) -> None:
        """Oddiy matnli alert — TZ 9.1 (muhim/batafsil filtri)."""
        async with self.session_factory() as session:
            if not important and not await is_verbose(session):
                return
        await self._broadcast(message)

    async def send_image_warning(self, message: str, tg_user_id: int, tg_username: str | None) -> None:
        """TZ 5.1 — kupon o'rniga rasm kelganda, har doim yuboriladi (muhim)."""
        markup = InlineKeyboardMarkup(inline_keyboard=[[_open_chat_button(tg_user_id, tg_username)]])
        await self._broadcast(message, markup)

    async def send_suspicious_alert(
        self, message: str, case_id: int, tg_user_id: int, tg_username: str | None
    ) -> None:
        """TZ 5.2 — bir nomer turli akkauntdan; har doim yuboriladi (muhim)."""
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [_open_chat_button(tg_user_id, tg_username)],
                [
                    InlineKeyboardButton(text="✅ Xavfsiz", callback_data=f"safe:{case_id}"),
                    InlineKeyboardButton(text="🚫 Bloklash", callback_data=f"block:{case_id}"),
                ],
            ]
        )
        await self._broadcast(message, markup)

    async def _broadcast(self, message: str, markup: InlineKeyboardMarkup | None = None) -> None:
        async with self.session_factory() as session:
            admin_ids = await list_admin_tg_ids(session)

        if self._bot is None:
            log.info("ADMIN ALERT: %s", message)
            return

        for tg_id in admin_ids:
            try:
                await self._bot.send_message(tg_id, message, reply_markup=markup)
            except Exception:
                log.exception("Adminga xabar yuborib bo'lmadi (tg_id=%s)", tg_id)
