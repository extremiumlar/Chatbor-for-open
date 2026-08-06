"""openbudget.uz ovozlarini SQLite'ga yozadigan qo'lda ishga tushiriladigan skript.

Ishlatish (captchani AVVAL brauzerda o'zingiz yeching):

    1. Tashabbus sahifasini oching -> "Овозларни кўриш" -> captchani yeching.
    2. DevTools -> Console:  localStorage.getItem("initToken")
    3. Chiqqan qiymatni `.env` ga yozing:
           OPENBUDGET_INITIATIVE_ID=4b377184-72c0-4ab6-854f-a5d912cdf506
           OPENBUDGET_VOTE_TOKEN=<yuqoridagi token>
    4. python -m scripts.sync_openbudget_votes

Token umri qisqa (~2 daqiqa), shuning uchun katta tashabbus bitta tokenga
sig'masligi mumkin. Token o'rtada tugasa skript o'qib ulgurganini bazada
QOLDIRADI va qaysi sahifadan davom etish kerakligini aytadi:

    python -m scripts.sync_openbudget_votes --start-page 37

(yangi token olib, `.env` dagi OPENBUDGET_VOTE_TOKEN ni yangilagach).
"""

import argparse
import asyncio
import logging
import sys

from core.config import settings
from core.db import get_session, init_db
from core.logic.openbudget import (
    OpenBudgetVotesClient,
    VoteTokenExpiredError,
    sync_votes,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start-page",
        type=int,
        default=0,
        help="Qaysi sahifadan boshlash (uzilgan sinxronizatsiyani davom ettirish uchun).",
    )
    args = parser.parse_args()

    initiative_id = settings.openbudget_initiative_id
    token = settings.openbudget_vote_token
    if not initiative_id or not token:
        print(
            "OPENBUDGET_INITIATIVE_ID va OPENBUDGET_VOTE_TOKEN .env da to'ldirilmagan "
            "— yuqoridagi izohdagi qadamlarni bajaring.",
            file=sys.stderr,
        )
        return 2

    await init_db()
    try:
        async with OpenBudgetVotesClient(token, base_url=settings.openbudget_base_url) as client:
            async with get_session() as session:
                inserted, seen = await sync_votes(
                    session,
                    client,
                    initiative_id,
                    start_page=args.start_page,
                    page_delay_seconds=settings.openbudget_page_delay_seconds,
                )
    except VoteTokenExpiredError as exc:
        print(
            f"TOKEN ESKIRGAN: {exc}\n"
            f"Shu sahifagacha o'qilgani bazada saqlandi. Yangi token olib davom eting:\n"
            f"    python -m scripts.sync_openbudget_votes --start-page {exc.page}",
            file=sys.stderr,
        )
        return 3

    print(f"Tayyor: {seen} ta ovoz ko'rildi, {inserted} tasi yangi yozildi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
