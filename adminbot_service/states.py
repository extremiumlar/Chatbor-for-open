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
