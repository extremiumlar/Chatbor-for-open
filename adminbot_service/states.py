"""FSM holatlari — tugmali interfeys ko'p qadamli oqimlari uchun.

Admin buyruq sintaksisini eslab qolmasligi kerak: tugma bosiladi, bot
"nima kiritish kerakligini" so'raydi, admin faqat qiymatni yozadi.
"""

from aiogram.fsm.state import State, StatesGroup


class AddBotFlow(StatesGroup):
    waiting_username = State()


class EditTemplateFlow(StatesGroup):
    waiting_text = State()


class EditPatternFlow(StatesGroup):
    waiting_text = State()


class SearchFlow(StatesGroup):
    waiting_phone = State()


class UserNoteFlow(StatesGroup):
    waiting_note = State()


# Audit J-9 (TZ 2.2, 4.1) — operator kodlari va mijoz-timeout endi
# Adminbot orqali jonli sozlanadi.
class EditOperatorCodesFlow(StatesGroup):
    waiting_text = State()


class EditTimeoutFlow(StatesGroup):
    waiting_text = State()
