"""Fon vazifalari kuzatuvchisi — TZ v2 4.3 ruhida ("jimgina yo'qolish"ga qarshi).

Muammo. `asyncio.create_task(...)` bilan ko'tarilgan cheksiz sikl xato bilan
tugasa, hech kim buni sezmaydi:

* natijasi hech qachon `await` qilinmaydi;
* vazifaga havola ro'yxatda saqlanib turgani uchun u axlat yig'ilmaydi va
  Python'ning "Task exception was never retrieved" ogohlantirishi ham
  CHIQMAYDI;
* jarayonning o'zi tirik qolaveradi.

Natija: xizmat sog'lomdek ko'rinadi, lekin taymerlar butunlay to'xtaydi.
Jonli sinovda aynan shu bo'ldi — poller 15:54 da ishlagan, 16:27 dagi
rasmsizlik eslatmasini esa bajarmagan; logda bir og'iz xato yo'q edi va
muammo faqat bazadagi `scheduled_jobs` ni qo'lda ko'rganda topildi.

Yechim: har fon sikli shu kuzatuvchi ichida ishlaydi. Sikl tugasa (xato
bilan ham, jimgina ham) — superadminga alert ketadi va sikl qayta
ko'tariladi.
"""

import asyncio
import logging
import time
from typing import Awaitable, Callable

log = logging.getLogger("supervisor")

# Sikl shuncha vaqt muammosiz ishlagan bo'lsa, uzilish "tasodifiy" deb
# hisoblanadi va kutish oralig'i boshlang'ich holatga qaytariladi. Aks holda
# kuniga bir marta uziladigan sikl ham asta-sekin eng katta kechikishga
# yetib borardi.
_BARQAROR_ISH_SONIYA = 120.0


async def _ogohlantir(alert_sink, matn: str) -> None:
    """Alert yuborishning o'zi xato bersa (tarmoq yo'q, Telegram javob
    bermayapti) kuzatuvchi o'lib qolmasligi kerak — aks holda tuzatish
    o'zi tuzatmoqchi bo'lgan muammoni takrorlagan bo'lardi."""
    if alert_sink is None:
        return
    try:
        await alert_sink(matn, True)
    except Exception:
        log.exception("Kuzatuvchi alertini yuborib bo'lmadi")


async def supervise(
    name: str,
    factory: Callable[[], Awaitable[None]],
    alert_sink=None,
    *,
    first_delay: float = 5.0,
    max_delay: float = 300.0,
) -> None:
    """Cheksiz fon siklini kuzatadi va tugab qolsa qayta ko'taradi.

    `factory` — HAR SAFAR YANGI korutina qaytaradigan funksiya (`lambda:
    poller.run_loop()` kabi). Tayyor korutina berib bo'lmaydi: bitta
    korutinani ikki marta `await` qilib bo'lmaydi, ya'ni qayta ko'tarish
    imkonsiz bo'lardi.

    To'xtatish (`task.cancel()`) hurmat qilinadi: `CancelledError` ushlanmaydi,
    yuqoriga o'tkaziladi — aks holda xizmatni o'chirib bo'lmasdi.
    """
    delay = first_delay
    while True:
        boshlandi = time.monotonic()
        try:
            await factory()
        except asyncio.CancelledError:
            # Bu — xato emas, to'xtatish buyrug'i (Ctrl+C / systemd stop).
            raise
        except Exception as exc:
            sabab = f"xato bilan to'xtadi: {exc!r}"
            log.exception("Fon vazifasi '%s' xato bilan to'xtadi", name)
        else:
            # Cheksiz sikl o'z-o'zidan tugashi — bu ham nosozlik.
            sabab = "kutilmaganda tugadi (cheksiz sikl bo'lishi kerak edi)"
            log.error("Fon vazifasi '%s' %s", name, sabab)

        if time.monotonic() - boshlandi >= _BARQAROR_ISH_SONIYA:
            delay = first_delay

        await _ogohlantir(
            alert_sink,
            f"🔴 Fon vazifasi <b>{name}</b> {sabab}\n"
            f"{delay:.0f} soniyadan keyin qayta ko'tariladi.\n\n"
            f"<i>Bu vazifa to'xtaganda tizim tashqaridan sog'lomdek "
            f"ko'rinadi, lekin unga bog'liq ishlar bajarilmay qoladi.</i>",
        )

        await asyncio.sleep(delay)
        delay = min(delay * 2, max_delay)
        log.info("Fon vazifasi '%s' qayta ko'tarilmoqda.", name)


def spawn_supervised(
    name: str,
    factory: Callable[[], Awaitable[None]],
    alert_sink=None,
    **kwargs,
) -> asyncio.Task:
    """`supervise` ni vazifa sifatida ko'taradi (nomi bilan — tashxis uchun)."""
    return asyncio.create_task(supervise(name, factory, alert_sink, **kwargs), name=name)
