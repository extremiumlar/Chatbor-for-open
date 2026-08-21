"""Fon vazifalari kuzatuvchisi — `core/logic/supervisor.py`.

Nega bu testlar bor: jonli sinovda poller xato bilan o'lgan va NA logda,
NA alertda hech qanday iz qolmagan. Jarayon tirik, xizmat sog'lomdek
ko'rinardi, lekin taymerlar to'xtagan edi. Muammo faqat bazadagi
`scheduled_jobs` ni qo'lda ko'rganda topildi.
"""

import asyncio

import pytest

from core.logic.supervisor import spawn_supervised, supervise


@pytest.fixture
def alerts():
    """Superadminga ketgan alertlarni ushlaydi."""
    yozilganlar: list[str] = []

    async def sink(matn: str, important: bool = True) -> None:
        yozilganlar.append(matn)

    sink.yozilganlar = yozilganlar
    return sink


async def test_crashed_loop_is_restarted(alerts):
    """Sikl xato bilan tugasa — qayta ko'tarilishi kerak."""
    urinishlar = []

    async def sinuvchi_sikl():
        urinishlar.append(1)
        if len(urinishlar) < 3:
            raise RuntimeError("tarmoq uzildi")
        await asyncio.Event().wait()  # uchinchisida barqaror ishlaydi

    task = spawn_supervised("sinov", sinuvchi_sikl, alerts, first_delay=0.01)
    await asyncio.sleep(0.2)
    task.cancel()

    assert len(urinishlar) == 3, "sikl qayta ko'tarilmadi"
    # Har o'lim uchun alohida alert.
    assert len(alerts.yozilganlar) == 2
    assert "sinov" in alerts.yozilganlar[0]
    assert "tarmoq uzildi" in alerts.yozilganlar[0]


async def test_silently_finished_loop_also_alerts(alerts):
    """Cheksiz sikl xatosiz tugab qolsa ham — bu nosozlik.

    Aynan shu holat eng xavflisi: hech qanday istisno yo'q, demak eski
    kodda mutlaqo hech qayerda iz qolmasdi.
    """
    sonagich = []

    async def darhol_tugaydigan():
        sonagich.append(1)
        return  # cheksiz bo'lishi kerak edi

    task = spawn_supervised("jim_o'lim", darhol_tugaydigan, alerts, first_delay=0.01)
    await asyncio.sleep(0.1)
    task.cancel()

    assert len(sonagich) > 1, "jimgina tugagan sikl qayta ko'tarilmadi"
    assert alerts.yozilganlar
    assert "kutilmaganda tugadi" in alerts.yozilganlar[0]


async def test_cancel_stops_the_supervisor(alerts):
    """To'xtatish buyrug'i (Ctrl+C / systemd stop) hurmat qilinishi kerak —
    aks holda xizmatni o'chirib bo'lmasdi."""
    ishga_tushdi = asyncio.Event()

    async def uzoq_sikl():
        ishga_tushdi.set()
        await asyncio.Event().wait()

    task = spawn_supervised("uzoq", uzoq_sikl, alerts, first_delay=0.01)
    await asyncio.wait_for(ishga_tushdi.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert alerts.yozilganlar == [], "to'xtatish xato deb hisoblandi"


async def test_alert_failure_does_not_kill_the_supervisor():
    """Alert yuborishning o'zi yiqilsa (tarmoq yo'q), kuzatuvchi o'lmasligi
    kerak — aks holda tuzatish o'zi tuzatmoqchi bo'lgan muammoni
    takrorlagan bo'lardi."""
    urinishlar = []

    async def yiqiluvchi_alert(matn: str, important: bool = True) -> None:
        raise ConnectionError("Telegram javob bermayapti")

    async def sinuvchi_sikl():
        urinishlar.append(1)
        raise RuntimeError("xato")

    task = spawn_supervised("sinov", sinuvchi_sikl, yiqiluvchi_alert, first_delay=0.01)
    await asyncio.sleep(0.15)
    task.cancel()

    assert len(urinishlar) > 1, "alert xatosi kuzatuvchini o'ldirdi"


async def test_backoff_grows_then_resets_after_stable_run(alerts, monkeypatch):
    """Ketma-ket yiqilishda kutish oralig'i o'sadi (alert bo'roni bo'lmasin),
    lekin sikl barqaror ishlagach boshlang'ich holatga qaytadi."""
    import core.logic.supervisor as sup

    kechikishlar = []
    haqiqiy_sleep = asyncio.sleep

    async def soxta_sleep(sekund):
        kechikishlar.append(sekund)
        await haqiqiy_sleep(0)

    monkeypatch.setattr(sup.asyncio, "sleep", soxta_sleep)

    async def doim_yiqiladi():
        raise RuntimeError("x")

    task = asyncio.create_task(
        supervise("o'suvchi", doim_yiqiladi, alerts, first_delay=1.0, max_delay=8.0)
    )
    await haqiqiy_sleep(0.05)
    task.cancel()

    # 1, 2, 4, 8, 8, ... — ikki barobar o'sib, chegarada to'xtaydi.
    assert kechikishlar[:4] == [1.0, 2.0, 4.0, 8.0], kechikishlar[:6]
    assert max(kechikishlar) == 8.0
