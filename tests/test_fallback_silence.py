"""Adminbot noo'rin joyda "Sizda ruxsat yo'q" deb javob bermasin.

Foydalanuvchi shikoyati: "har lichkada o'zi nomer tashaganda sizda ruxsat
yoq deb chiqib qolyapti". Takrorlanganda ma'lum bo'ldiki, muammo undan
kengroq — NAZORAT GURUHIDA ham chiqardi, hatto OWNER tashlagan rasm
caption'iga ham.

Sabab: `IsAdmin` `False` qaytarganda xabar `admin_router`dan o'tmaydi va
`fallback_router` ga tushadi, u esa HAMMAGA javob berardi. Guruhda
`should_handle_in_chat` buyruq bo'lmagan xabarni ataylab to'sadi (T-4) —
lekin to'silgan xabar shu yerda javob olib, guruhni ifloslantirardi.
Ya'ni "guruhda jim tur" qoidasi amalda ishlamagan, faqat javob matni
"Tushunmadim" dan "Sizda ruxsat yo'q" ga o'zgargan.
"""

import datetime

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import Chat, Message, User as TgUser

from core.models import Admin, AdminRole

ADMIN_TG = 6644467393
MIJOZ_TG = 7777777777
GURUH = -1004363150995


def _msg(text, uid, chat_id, chat_type):
    return Message(
        message_id=1,
        date=datetime.datetime.now(),
        chat=Chat(id=chat_id, type=chat_type),
        from_user=TgUser(id=uid, is_bot=False, first_name="X"),
        text=text,
    )


@pytest.fixture
def yubor(session_factory, monkeypatch):
    """Xabarni HAQIQIY router zanjiridan o'tkazadi (admin -> fallback)."""
    import adminbot_service.bot as ab

    javoblar: list[str] = []

    async def fake_answer(self, text="", **kw):
        javoblar.append(text)
        return None

    monkeypatch.setattr(ab, "get_session", session_factory)
    monkeypatch.setattr(Message, "answer", fake_answer, raising=False)
    monkeypatch.setattr(Message, "reply", fake_answer, raising=False)
    ab._denied_told.clear()

    async def _yubor(m) -> list[str]:
        javoblar.clear()
        res = await ab.admin_router.propagate_event(
            "message", m, bot=None, event_update=None, state=None
        )
        if res is UNHANDLED:
            await ab.fallback_router.propagate_event(
                "message", m, bot=None, event_update=None, state=None
            )
        return list(javoblar)

    return _yubor


@pytest.fixture
async def owner(session_factory):
    async with session_factory() as session:
        session.add(
            Admin(id=1, tg_user_id=ADMIN_TG, name="Owner", role=AdminRole.OWNER)
        )
        await session.commit()


# --------------------------------------------------------------------------- #
# Guruh — mutlaq jimlik
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "matn",
    [
        "📸 #C11\n📱 +998 88 246 21 05",   # forward qilingan rasm caption'i
        "ha yaxshi",                        # adminlarning oddiy suhbati
        "998901234567",                     # guruhga tashlangan nomer
    ],
)
async def test_group_stays_silent(session_factory, owner, yubor, matn):
    """Nazorat guruhi TOZA ARXIV bo'lishi kerak (TZ v2 5.2).

    Jonli sinovda har rasm partiyasidan keyin 2-3 ta chiqindi javob
    chiqardi — kuniga ~140 ta.
    """
    javoblar = await yubor(_msg(matn, ADMIN_TG, GURUH, "supergroup"))

    assert javoblar == [], f"guruhga javob ketdi: {javoblar}"


async def test_group_commands_still_work(session_factory, owner, yubor):
    """Jimlik faqat buyruq BO'LMAGAN xabarlarga — buyruqlar ishlashi kerak."""
    javoblar = await yubor(_msg("/stats", ADMIN_TG, GURUH, "supergroup"))

    assert javoblar and "Statistika" in javoblar[0]


# --------------------------------------------------------------------------- #
# Lichka — begonaga bir marta, tushunarli qilib
# --------------------------------------------------------------------------- #


async def test_stranger_is_told_once(session_factory, owner, yubor):
    """Mijoz botni topib yozsa — sababni bilishi kerak, lekin FAQAT
    bir marta (har xabariga javob spam bo'lardi)."""
    birinchi = await yubor(_msg("998901234567", MIJOZ_TG, MIJOZ_TG, "private"))
    ikkinchi = await yubor(_msg("salom", MIJOZ_TG, MIJOZ_TG, "private"))
    uchinchi = await yubor(_msg("javob bering", MIJOZ_TG, MIJOZ_TG, "private"))

    assert birinchi and "faqat xizmat adminlari uchun" in birinchi[0]
    assert ikkinchi == [], "ikkinchi xabarga ham javob ketdi"
    assert uchinchi == []


async def test_stranger_message_is_not_scary(session_factory, owner, yubor):
    """Eski matn "Sizda ruxsat yo'q" edi — mijozga bu qo'rqinchli va
    tushunarsiz. Endi nima qilish kerakligi aytiladi."""
    javoblar = await yubor(_msg("assalomu alaykum", MIJOZ_TG, MIJOZ_TG, "private"))

    assert javoblar
    assert "ruxsat yo'q" not in javoblar[0].lower()
    assert "adminga yozing" in javoblar[0].lower()


async def test_admin_in_private_is_unaffected(session_factory, owner, yubor):
    """Regressiya: haqiqiy admin lichkada avvalgidek ishlashi kerak."""
    javoblar = await yubor(_msg("998901234567", ADMIN_TG, ADMIN_TG, "private"))

    assert javoblar
    assert "faqat xizmat adminlari" not in javoblar[0]


async def test_cooldown_expires(session_factory, owner, yubor, monkeypatch):
    """Sovutish oralig'i o'tgach begona yana javob olishi kerak — aks holda
    bir marta yozgan odam abadiy javobsiz qolardi."""
    import adminbot_service.bot as ab

    await yubor(_msg("salom", MIJOZ_TG, MIJOZ_TG, "private"))
    # Vaqtni orqaga suramiz — sovutish o'tgan holat.
    ab._denied_told[MIJOZ_TG] = datetime.datetime.utcnow() - datetime.timedelta(
        minutes=ab._DENIED_COOLDOWN_MINUTES + 1
    )

    javoblar = await yubor(_msg("salom", MIJOZ_TG, MIJOZ_TG, "private"))

    assert javoblar, "sovutish o'tgandan keyin ham jim qoldi"
