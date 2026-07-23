"""Restart reconciliation — TZ 12-bo'lim (Q37).

Tizim (Teleton) qayta ishga tushganda (masalan jarayon kutilmagan holda
o'chib qolgan bo'lsa) yarim qolgan case'lar bo'lishi mumkin:

- Bot bilan muloqot davomida (SENT_TO_BOT/AWAITING_COUPON/COUPON_SENT_TO_BOT)
  to'xtab qolgan case'lar — natija noaniq (bot ehtimol tasdiqlagan bo'lishi
  mumkin, lekin jarayonimiz buni bilmay qoldi). TZ "ehtimol tasdiqlangan deb
  belgilab, admin ko'rib chiqishi kerak" deydi; yangi status qo'shish
  taqiqlangani uchun mavjud `NEEDS_ADMIN` shu maqsadda qayta ishlatiladi —
  "noaniq holat, admin aralashuvi kerak" ta'rifiga aynan mos keladi.
- `NUMBER_RECEIVED` (navbatda, hali botga hech narsa yuborilmagan) case'lar —
  hech qanday ma'lumot yo'qolmagan, xavfsiz qayta dispatch qilinadi.

Mijoz kutish taymerlari (asyncio task, 5-daqiqa) restart paytida yo'qoladi
(faqat xotirada saqlanadi) — shuning uchun band bo'lib qolgan case'larni
avtomatik davom ettirishning iloji yo'q, ular NEEDS_ADMIN'ga o'tkaziladi.
"""

import logging

from sqlalchemy import select

from core.enums import CaseStatus
from core.models import Case, User

log = logging.getLogger("reconciliation")

_STUCK_STATUSES = (CaseStatus.SENT_TO_BOT, CaseStatus.AWAITING_COUPON, CaseStatus.COUPON_SENT_TO_BOT)


async def reconcile_after_restart(case_manager, session_factory, alert_sink, notify_customer) -> None:
    async with session_factory() as session:
        stuck_result = await session.execute(select(Case).where(Case.status.in_(_STUCK_STATUSES)))
        stuck_cases = stuck_result.scalars().all()

        for case in stuck_cases:
            bot_id = case.bot_id
            case.status = CaseStatus.NEEDS_ADMIN
            await session.commit()
            if bot_id is not None:
                await case_manager.pool.force_release(session, bot_id)
            await alert_sink(
                f"RESTART: Case #{case.id} tizim qayta ishga tushganda yarim qolgan holatda "
                f"topildi (ehtimol tasdiqlangan bo'lishi mumkin, aniq emas) — qo'lda tekshiring.",
                True,
            )

        queued_result = await session.execute(
            select(Case).where(Case.status == CaseStatus.NUMBER_RECEIVED).order_by(Case.id)
        )
        queued_cases = queued_result.scalars().all()

    for case in queued_cases:
        async with session_factory() as session:
            fresh_case = await session.get(Case, case.id)
            user = await session.get(User, fresh_case.user_id)
            outcome = await case_manager.redispatch_queued_case(session, fresh_case)
            if outcome.customer_text:
                await notify_customer(user.tg_user_id, outcome.customer_text)

    if stuck_cases or queued_cases:
        log.info(
            "Reconciliation: %d yarim qolgan case NEEDS_ADMIN'ga o'tkazildi, "
            "%d navbatdagi case qayta dispatch qilindi.",
            len(stuck_cases),
            len(queued_cases),
        )
