"""Shablonlarning "ishlaydi / o'lik" ro'yxati kod bilan mos ekanini tekshiradi.

Nega kerak: `V2_ACTIVE_KEYS` — QO'LDA yozilgan ro'yxat. Qo'lda yozilgan har
qanday ro'yxat ertami-kech kod bilan chetlashadi (aynan shu sabab
`permissions.py` da ham bor). Chetlashsa oqibati og'ir: admin "ishlaydi"
deb belgilangan shablonni tahrirlaydi, matn esa mijozga bormaydi — jonli
sinovda `CONFIRMED` bilan aynan shunday bo'lgan.

Shuning uchun ro'yxat kod MANBASIDAN olinadi va solishtiriladi.
"""

import ast
import pathlib

import pytest

from core.logic.templates import (
    DEFAULTS,
    V2_ACTIVE_KEYS,
    V2_LEGACY_KEYS,
    is_active,
)

# v2 oqimi ishlaydigan modullar — mijozga matn shulardan ketadi.
_V2_MODULLAR = (
    "core/logic/screenshots.py",
    "core/logic/result_flow.py",
    "core/logic/manual_case.py",
    "core/logic/job_poller.py",
    "core/logic/check_engine.py",
    "teleton_service/manual_relay.py",
)


def _koddan_ishlatilgan_kalitlar() -> set[str]:
    """`get_template(session, "KEY")` chaqiruvlarini AST orqali yig'adi.

    Matn qidiruvi emas, AST — izohdagi yoki o'chirilgan koddagi kalit
    yolg'on "ishlatilyapti" degan xulosa bermasligi uchun.
    """
    topilgan: set[str] = set()
    for yol in _V2_MODULLAR:
        daraxt = ast.parse(pathlib.Path(yol).read_text(encoding="utf-8"))
        for node in ast.walk(daraxt):
            if not isinstance(node, ast.Call):
                continue
            nom = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if nom != "get_template":
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    topilgan.add(arg.value)
    return topilgan


def test_active_list_matches_the_code():
    """`V2_ACTIVE_KEYS` kodda haqiqatan chaqirilayotgan kalitlar bilan
    AYNAN bir xil bo'lishi kerak."""
    koddagi = _koddan_ishlatilgan_kalitlar()

    yetishmayotgan = koddagi - set(V2_ACTIVE_KEYS)
    ortiqcha = set(V2_ACTIVE_KEYS) - koddagi

    assert not yetishmayotgan, (
        "Kod bu shablonlarni yuboradi, lekin ular 'ishlaydi' ro'yxatida yo'q "
        f"(admin ularni 💤 deb ko'radi va tahrirlamaydi): {sorted(yetishmayotgan)}"
    )
    assert not ortiqcha, (
        "Bu shablonlar 'ishlaydi' deb belgilangan, lekin kod ularni hech "
        f"qachon yubormaydi (admin bekorga tahrirlaydi): {sorted(ortiqcha)}"
    )


def test_legacy_keys_are_the_rest():
    """Har bir shablon aniq bir guruhda bo'lsin — orada qolgani bo'lmasin."""
    assert set(V2_ACTIVE_KEYS) | set(V2_LEGACY_KEYS) == set(DEFAULTS)
    assert not set(V2_ACTIVE_KEYS) & set(V2_LEGACY_KEYS)


@pytest.mark.parametrize("key", ["SCREENSHOT_FOLLOWUP", "RESULT_PASSED", "RESULT_FAILED"])
def test_known_active(key):
    assert is_active(key)


@pytest.mark.parametrize("key", ["CONFIRMED", "COUPON_REQUEST", "REJECTED"])
def test_known_legacy(key):
    """`CONFIRMED` — jonli sinovda adashtirgan aynan shu shablon."""
    assert not is_active(key)


def test_legacy_templates_are_not_deleted():
    """O'lik shablonlar ro'yxatdan CHIQARILMAYDI — v1 kodi ularga hali
    murojaat qiladi va o'chirilsa `KeyError` bilan yiqilardi."""
    for key in V2_LEGACY_KEYS:
        assert key in DEFAULTS


def test_keyboard_separates_active_from_legacy():
    """Ro'yxatda ishlaydiganlari yuqorida, o'liklari ajratgich ostida."""
    from adminbot_service.keyboards import template_keys

    markup = template_keys(DEFAULTS.keys(), "c")
    matnlar = [b.text for row in markup.inline_keyboard for b in row]

    ajratgich = next(i for i, t in enumerate(matnlar) if "ishlatilmaydi" in t)
    faol_indekslar = [i for i, t in enumerate(matnlar) if t.startswith("✅")]
    olik_indekslar = [i for i, t in enumerate(matnlar) if t.startswith("💤")]

    assert faol_indekslar and olik_indekslar
    assert max(faol_indekslar) < ajratgich < min(olik_indekslar)
    # Bot-tanish shablonlarida bunday bo'linish yo'q (u yerda hammasi kerak).
    bot_markup = template_keys(["A", "B"], "b")
    assert not any("ishlatilmaydi" in b.text for row in bot_markup.inline_keyboard for b in row)
