"""openbudget.uz "Овозларни кўриш" ro'yxatini o'qib SQLite'ga yozadi.

Saytning ichki API zanjiri (frontend bundle'idan aniqlangan —
`assets/index-c30f7f61.js`, `VoteModalView-*.js`):

    1. GET  /api/v2/vote/captcha-2              -> {image, captchaKey}
    2. POST /api/v2/info/get-initiative-token   <- {initiativeId, captchaKey, captchaResult}
                                                -> {token, date}
    3. GET  /api/v2/info/votes/{token}?page=N   -> {content: [...], totalElements: N}

MUHIM — 1-2 qadamlar CAPTCHA bilan himoyalangan va bu modul ularni
BAJARMAYDI. Captchani odam brauzerda yechadi, hosil bo'lgan `token`ni
(brauzerda `localStorage.initToken`) tizimga beradi; bu modul faqat
3-qadamni — allaqachon berilgan token bilan ro'yxatni o'qishni — bajaradi.
Token eskirganda API `410 Gone` qaytaradi (frontend ham aynan shunda yangi
captcha so'raydi) — bunda `VoteTokenExpiredError` ko'tariladi va chaqiruvchi
admindan yangi token so'rashi kerak.

Nomer ro'yxatda MASKALANGAN holda keladi (faqat oxirgi 4 raqam) — shuning
uchun mos kelish kupon egasini ISBOTLAMAYDI, faqat ishora beradi.
"""

import asyncio
import datetime
import json
import logging
import re

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import OpenBudgetVote

log = logging.getLogger("openbudget")

DEFAULT_BASE_URL = "https://openbudget.uz/api"

# Sayt oddiy brauzerdan kelmagan so'rovlarni rad etishi mumkin — Referer
# aynan tashabbus sahifasiga ishora qilgani xavfsizroq.
_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://openbudget.uz/",
}

_DIGITS_RE = re.compile(r"\d")

# Frontend tokenni `date + 120000ms` gacha yaroqli deb hisoblaydi
# (`InitiativeView-*.js`: sessionTokenDate, keyin "N daqiqa M soniyadan keyin
# urinib ko'ring" sanog'i). Bu SERVER kafolati emas — faqat sayt frontendining
# taxmini; haqiqiy muddat uzunroq bo'lishi ham mumkin. Kod shu qiymatga
# TAYANMAYDI: yagona ishonchli signal — 410 javobi.
TOKEN_TTL_SECONDS = 120


class OpenBudgetError(Exception):
    """openbudget.uz API bilan ishlashda umumiy xato."""


class VoteTokenExpiredError(OpenBudgetError):
    """Token eskirgan/yaroqsiz (HTTP 410) — yangi captcha yechish kerak.

    `page` — uzilish RO'Y BERGAN sahifa raqami. Token umri qisqa (frontend
    2 daqiqa deb hisoblaydi, pastdagi TOKEN_TTL_SECONDS izohiga qarang),
    shuning uchun katta tashabbusni bitta token bilan oxirigacha o'qib
    bo'lmasligi MUMKIN. Shu maydon orqali chaqiruvchi yangi token olib
    aynan shu sahifadan davom ettiradi — boshidan boshlash shart emas.
    """

    def __init__(self, message: str, *, page: int = 0) -> None:
        super().__init__(message)
        self.page = page


def extract_last4(phone_masked: str) -> str | None:
    """Maskalangan nomerdan oxirgi 4 raqamni ajratadi.

    Sayt formatini o'zgartirishi mumkin ("**** 1234", "+998 ** *** 12 34",
    "9985678"), shuning uchun aniq shablonga emas — matndagi BARCHA
    raqamlarni yig'ib, oxirgi 4 tasini olamiz. Bu bo'shliq/tire bilan
    ajratilgan ("12 34") ko'rinishlarda ham to'g'ri ishlaydi.

    4 ta raqam topilmasa None (yozuv baribir `raw` bilan saqlanadi).
    """
    digits = "".join(_DIGITS_RE.findall(phone_masked or ""))
    return digits[-4:] if len(digits) >= 4 else None


def _parse_vote_date(value: str) -> datetime.datetime | None:
    """Sayt qaytargan sanani datetime'ga o'giradi; tanimasa None.

    Aniq format hali real javobda tasdiqlanmagan — shuning uchun bir nechta
    ehtimoliy ko'rinish sinaladi va muvaffaqiyatsizlik XATO EMAS (xom qiymat
    `voted_at_raw`da qoladi, keyin qayta talqin qilish mumkin).
    """
    if not value:
        return None
    text = value.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.datetime.strptime(text[: len(fmt) + 6], fmt)
        except ValueError:
            continue
    try:  # ISO-8601 (millisekund/timezone bilan)
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


class OpenBudgetVotesClient:
    """Faqat O'QIYDI: berilgan token bilan ovozlar ro'yxatini sahifalab oladi."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not token:
            raise OpenBudgetError(
                "Token bo'sh — captchani brauzerda yechib, localStorage.initToken "
                "qiymatini OPENBUDGET_VOTE_TOKEN sifatida bering."
            )
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "OpenBudgetVotesClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout, headers=_HEADERS)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_page(self, page: int) -> tuple[list[dict], int]:
        """Bitta sahifani o'qiydi -> (yozuvlar, jami soni)."""
        if self._client is None:
            raise OpenBudgetError("Klient `async with` ichida ishlatilishi kerak.")

        url = f"{self._base_url}/v2/info/votes/{self._token}"
        response = await self._client.get(url, params={"page": page})

        if response.status_code == 410:
            raise VoteTokenExpiredError(
                f"openbudget.uz tokeni eskirgan (410 Gone, sahifa {page}) — captchani "
                "qayta yechib yangi token kiritish kerak.",
                page=page,
            )
        if response.status_code >= 400:
            raise OpenBudgetError(
                f"openbudget.uz {response.status_code} qaytardi (page={page}): "
                f"{response.text[:200]}"
            )

        payload = response.json()
        items = payload.get("content") or []
        total = int(payload.get("totalElements") or 0)
        return items, total


def _normalize(item: dict, initiative_id: str) -> dict | None:
    """API yozuvini jadval ustunlariga moslaydi; nomer topilmasa None."""
    phone_masked = str(item.get("phoneNumber") or "").strip()
    if not phone_masked:
        return None
    voted_at_raw = str(item.get("voteDate") or "").strip()
    return {
        "initiative_id": initiative_id,
        "phone_masked": phone_masked,
        "phone_suffix": extract_last4(phone_masked) or "",
        "voted_at_raw": voted_at_raw,
        "voted_at": _parse_vote_date(voted_at_raw),
        "raw": json.dumps(item, ensure_ascii=False),
    }


async def sync_votes(
    session: AsyncSession,
    client: OpenBudgetVotesClient,
    initiative_id: str,
    *,
    start_page: int = 0,
    max_pages: int = 1000,
    page_delay_seconds: float = 0.0,
) -> tuple[int, int]:
    """Sahifalarni o'qib bazaga yozadi -> (yangi qo'shilgan, jami ko'rilgan).

    Idempotent: mavjud yozuv (`uq_openbudget_vote` uchligi bo'yicha) qayta
    qo'shilmaydi, shuning uchun sinxronizatsiyani xohlagancha qayta ishga
    tushirish (yoki yarmidan davom ettirish) mumkin.

    Har sahifadan keyin commit qilinadi — token o'rtada eskirsa (`410`)
    o'qib ulgurilgani BAZADA QOLADI, va `VoteTokenExpiredError.page`
    orqali yangi token bilan aynan o'sha sahifadan davom etish mumkin
    (`start_page`).

    `page_delay_seconds` standart 0 — token umri qisqa (~2 daqiqa,
    `TOKEN_TTL_SECONDS`), shuning uchun sekinlashtirish o'zini oqlamaydi:
    pauza qancha uzun bo'lsa, bitta token bilan shuncha kam sahifa o'qiladi.
    Sayt so'rov chastotasidan shikoyat qilsa shu qiymatni oshiring.
    """
    inserted = 0
    seen = 0
    page = start_page
    total = None

    page_size = None
    last_page = start_page + max_pages

    while page < last_page:
        items, reported_total = await client.fetch_page(page)
        if total is None:
            total = reported_total
            log.info("openbudget: tashabbus %s — jami %s ovoz", initiative_id, total)
        if not items:
            break
        # Sahifa hajmini serverning o'zi belgilaydi (`getVotes` `size`
        # yubormaydi) — birinchi javobdan aniqlanadi.
        if page_size is None:
            page_size = len(items)

        for item in items:
            seen += 1
            row = _normalize(item, initiative_id)
            if row is None:
                continue
            exists = await session.scalar(
                select(OpenBudgetVote.id).where(
                    OpenBudgetVote.initiative_id == row["initiative_id"],
                    OpenBudgetVote.phone_masked == row["phone_masked"],
                    OpenBudgetVote.voted_at_raw == row["voted_at_raw"],
                )
            )
            if exists is not None:
                continue
            session.add(OpenBudgetVote(**row))
            inserted += 1

        await session.commit()
        log.info(
            "openbudget: sahifa %s o'qildi (%s yozuv, jami ko'rilgan %s/%s)",
            page,
            len(items),
            seen,
            total,
        )

        # `seen` faqat SHU yurishni sanaydi — `start_page`dan davom etilganda
        # ro'yxatning boshi allaqachon o'qilgan, shuning uchun tugash sharti
        # ro'yxatdagi MUTLAQ o'ringa qarab hisoblanadi.
        #
        # Sahifa hajmi shu yurishning BIRINCHI javobidan olinadi. Davom
        # ettirishda (`start_page > 0`) o'sha javob to'liqsiz oxirgi sahifa
        # bo'lishi mumkin — u holda hajm kam baholanadi va sanoq tugash
        # nuqtasiga yetmaydi. Bu xavfsiz: sikl keyingi BO'SH sahifada
        # to'xtaydi, narxi — bitta ortiqcha so'rov.
        consumed = start_page * (page_size or 0) + seen
        if total is not None and consumed >= total:
            break
        page += 1
        if page_delay_seconds > 0:
            await asyncio.sleep(page_delay_seconds)

    return inserted, seen


async def find_votes_by_last4(
    session: AsyncSession, initiative_id: str, last4: str
) -> list[OpenBudgetVote]:
    """Nomerning oxirgi 4 raqami bo'yicha ovozlarni qidiradi (vaqti bo'yicha)."""
    result = await session.execute(
        select(OpenBudgetVote)
        .where(
            OpenBudgetVote.initiative_id == initiative_id,
            OpenBudgetVote.phone_suffix == last4,
        )
        .order_by(OpenBudgetVote.voted_at.desc())
    )
    return list(result.scalars().all())
