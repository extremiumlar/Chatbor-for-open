"""Aniqlanmagan nomlar (NameError) ishlab chiqarishga yetib bormasin.

Nega bu test bor: `manual_relay.on_incoming` ichida `chat_id` deb yozilgan
edi, holbuki o'sha qamrovda bunday o'zgaruvchi yo'q (to'g'risi
`event.chat_id`). Python buni faqat O'SHA QATOR bajarilganda sezadi —
import ham, testlar ham o'tib ketdi, xato esa jonli tizimda chiqdi:

    ERROR | telethon.client.updates | Unhandled exception on on_incoming
    NameError: name 'chat_id' is not defined

Natijada mijozdan kelgan HAR BIR matnsiz xabar shu xato bilan tugardi.

`symtable` moduli aynan shu tahlilni beradi: har qamrovda qaysi nom
lokal, qaysi biri tashqaridan olinayotganini aytadi. Tashqaridan
olinayotgani modul darajasida ham, ichki qurilgan nomlar orasida ham
bo'lmasa — bu aniqlanmagan nom.
"""

import builtins
import pathlib
import symtable

import pytest

# Butun loyiha tekshiriladi — bug bitta faylda chiqqan bo'lsa ham, xato
# turi umumiy.
_PAPKALAR = ("core", "teleton_service", "adminbot_service", "panel_service")


def _fayllar():
    for papka in _PAPKALAR:
        for yol in pathlib.Path(papka).rglob("*.py"):
            if "__pycache__" in yol.parts:
                continue
            yield yol


def _aniqlanmagan(yol: pathlib.Path) -> list[str]:
    manba = yol.read_text(encoding="utf-8")
    jadval = symtable.symtable(manba, str(yol), "exec")

    modul_nomlari = set(jadval.get_identifiers())
    ichki = set(dir(builtins))
    topilgan: list[str] = []

    def _yur(t: symtable.SymbolTable, ota_nomlar: set[str]):
        nomlar = ota_nomlar | set(t.get_identifiers())
        for sym in t.get_symbols():
            nom = sym.get_name()
            if sym.is_local() or sym.is_parameter() or sym.is_free():
                continue
            if not sym.is_referenced():
                continue
            # Global deb belgilangan, lekin modulda ham, ichki qurilganlar
            # orasida ham yo'q.
            if nom not in modul_nomlari and nom not in ichki:
                topilgan.append(f"{yol}:{t.get_name()}: {nom}")
        for bola in t.get_children():
            _yur(bola, nomlar)

    _yur(jadval, modul_nomlari)
    return topilgan


def test_no_undefined_names_in_the_codebase():
    hammasi: list[str] = []
    for yol in _fayllar():
        hammasi.extend(_aniqlanmagan(yol))

    assert not hammasi, (
        "Aniqlanmagan nom(lar) topildi — bular faqat o'sha qator "
        "bajarilganda NameError bo'lib chiqadi:\n  " + "\n  ".join(hammasi)
    )


def test_the_guard_actually_catches_the_bug(tmp_path):
    """Tekshiruvning O'ZI ishlashini isbotlaydi — aynan jonli tizimda
    chiqqan xato shakli bilan."""
    fayl = tmp_path / "namuna.py"
    fayl.write_text(
        "def on_incoming(event):\n"
        "    if _due(event.sender_id, chat_id):\n"   # <- aniqlanmagan
        "        return 1\n"
        "\n"
        "def _due(a, b):\n"
        "    return True\n",
        encoding="utf-8",
    )

    topilgan = _aniqlanmagan(fayl)

    assert any("chat_id" in t for t in topilgan), topilgan


def test_the_guard_does_not_flag_valid_code(tmp_path):
    """Yolg'on ogohlantirish bermasligi ham muhim — aks holda test
    o'chirib qo'yilardi."""
    fayl = tmp_path / "toza.py"
    fayl.write_text(
        "import os\n"
        "SOZLAMA = 1\n"
        "\n"
        "def tashqi(a):\n"
        "    ichki_qiymat = a + SOZLAMA\n"
        "    def ichki():\n"
        "        return ichki_qiymat + len(os.sep)\n"   # closure + import
        "    return ichki()\n"
        "\n"
        "class C:\n"
        "    def usul(self):\n"
        "        return [x for x in range(3)]\n",
        encoding="utf-8",
    )

    assert _aniqlanmagan(fayl) == []
