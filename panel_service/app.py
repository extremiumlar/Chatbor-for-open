"""Web panel — TZ 13-bo'lim ("Panel | Keyinchalik (FastAPI + web)"), 11.6
(qidiruv/filtr/statistika, mijozlar ro'yxati/tarixi — CRM ko'rinishi).

Faqat O'QISH uchun: qidiruv, filtr, statistika, tarix. Holat o'zgartiruvchi
amallar (shablon tahriri, bot qo'shish, bloklash va h.k.) Adminbot orqali
qoladi — ularni bu yerda takrorlash shart emas.

⚠️ Kirish oqimi (`/auth/telegram`, Telegram Login Widget) HAQIQIY Telegram
bilan sinalmagan — `panel_service/auth.py` boshidagi ogohlantirishga qarang.
"""

import datetime
import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

from core.config import settings
from core.db import get_session
from core.enums import CaseStatus
from core.logic.admins import can_see_everything, get_admin_by_tg_id, is_admin
from core.logic.audit import list_recent
from core.logic.case_search import search_cases
from core.logic.customers import cases_for_user, list_customers
from core.logic.stats import gather_stats
from core.models import Admin, Case, CouponAttempt, User
from panel_service.auth import verify_telegram_auth

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

app = FastAPI(title="Kupon Nazorat Paneli")
app.add_middleware(SessionMiddleware, secret_key=settings.panel_session_secret)


async def get_db():
    """FastAPI dependency — testlarda `app.dependency_overrides[get_db]`
    orqali izolyatsiyalangan bazaga almashtiriladi."""
    async with get_session() as session:
        yield session


class NotAuthenticated(Exception):
    pass


@app.exception_handler(NotAuthenticated)
async def _not_authenticated_handler(request: Request, exc: NotAuthenticated) -> RedirectResponse:
    return RedirectResponse(url="/login")


async def require_admin(request: Request, db: AsyncSession = Depends(get_db)) -> Admin:
    """Audit O-4 — avval faqat sessiya borligini tekshirardi; admin
    `admins` jadvalidan olib tashlansa ham eski sessiya orqali kirish
    davom etardi. Endi har so'rovda jadval qayta tekshiriladi. Audit K-4 —
    endi `int` emas, `Admin` qatorining o'zi qaytariladi (TZ 11.0/Q51
    ko'rish-cheklashi uchun rol kerak)."""
    tg_user_id = request.session.get("tg_user_id")
    if tg_user_id is None:
        raise NotAuthenticated()
    admin = await get_admin_by_tg_id(db, tg_user_id)
    if admin is None:
        request.session.clear()
        raise NotAuthenticated()
    return admin


# --------------------------------------------------------------------------- #
# Kirish — Telegram Login Widget (TZ 12.2: faqat `admins` jadvalidagi ID-lar)
# --------------------------------------------------------------------------- #


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "login.html", {"bot_username": settings.adminbot_username}
    )


@app.get("/auth/telegram")
async def auth_telegram(request: Request, db: AsyncSession = Depends(get_db)) -> RedirectResponse:
    data = dict(request.query_params)
    if not verify_telegram_auth(data, settings.adminbot_token):
        raise HTTPException(status_code=403, detail="Noto'g'ri yoki eskirgan Telegram tasdiqlash.")

    tg_user_id = int(data["id"])
    if not await is_admin(db, tg_user_id):
        raise HTTPException(status_code=403, detail="Siz admin ro'yxatida emassiz.")

    request.session["tg_user_id"] = tg_user_id
    request.session["display_name"] = data.get("first_name", "")
    return RedirectResponse(url="/")


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login")


# --------------------------------------------------------------------------- #
# Dashboard / statistika (TZ 10-bo'lim)
# --------------------------------------------------------------------------- #


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request, admin: Admin = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    stats = await gather_stats(db)
    return templates.TemplateResponse(request, "dashboard.html", {"stats": stats})


# --------------------------------------------------------------------------- #
# Audit (TZ 11.5, 12.2)
# --------------------------------------------------------------------------- #


@app.get("/audit", response_class=HTMLResponse)
async def audit_page(
    request: Request, admin: Admin = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    entries = await list_recent(db, limit=50)
    return templates.TemplateResponse(request, "audit.html", {"entries": entries})


# --------------------------------------------------------------------------- #
# Murojaatlar qidiruv/filtr + tafsilot (TZ 11.6)
# --------------------------------------------------------------------------- #


@app.get("/cases", response_class=HTMLResponse)
async def cases_page(
    request: Request,
    admin: Admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    phone: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> HTMLResponse:
    status_enum = CaseStatus(status) if status else None
    parsed_from = datetime.date.fromisoformat(date_from) if date_from else None
    parsed_to = datetime.date.fromisoformat(date_to) if date_to else None

    # Audit K-4 (TZ 11.0, Q51) — oddiy admin faqat o'ziga biriktirilgan
    # (yoki hali hech kimga biriktirilmagan) mijozlarning case'larini ko'radi.
    cases = await search_cases(
        db,
        phone=phone or None,
        status=status_enum,
        date_from=parsed_from,
        date_to=parsed_to,
        viewer_admin_id=admin.id,
        can_see_all=can_see_everything(admin),
    )

    return templates.TemplateResponse(
        request,
        "cases.html",
        {
            "cases": cases,
            "all_statuses": [s.value for s in CaseStatus],
            "filters": {"phone": phone, "status": status, "date_from": date_from, "date_to": date_to},
        },
    )


@app.get("/cases/{case_id}", response_class=HTMLResponse)
async def case_detail_page(
    request: Request,
    case_id: int,
    admin: Admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    case = await db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case topilmadi.")
    if not can_see_everything(admin):
        # Audit K-4 — boshqa adminga biriktirilgan mijozning case'i 404
        # bilan bir xil javob qaytaradi (mavjudligini oshkor qilmaslik uchun).
        owner = await db.get(User, case.user_id)
        if owner is not None and owner.assigned_admin_id not in (None, admin.id):
            raise HTTPException(status_code=404, detail="Case topilmadi.")
    attempts = (
        await db.execute(
            select(CouponAttempt).where(CouponAttempt.case_id == case_id).order_by(CouponAttempt.id)
        )
    ).scalars().all()

    return templates.TemplateResponse(request, "case_detail.html", {"case": case, "attempts": attempts})


# --------------------------------------------------------------------------- #
# Mijozlar — CRM ko'rinishi (TZ 11.6)
# --------------------------------------------------------------------------- #


@app.get("/customers", response_class=HTMLResponse)
async def customers_page(
    request: Request,
    admin: Admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    search: str | None = None,
) -> HTMLResponse:
    customers = await list_customers(
        db,
        search=search or None,
        viewer_admin_id=admin.id,
        can_see_all=can_see_everything(admin),
    )
    return templates.TemplateResponse(
        request, "customers.html", {"customers": customers, "search": search}
    )


@app.get("/customers/{user_id}", response_class=HTMLResponse)
async def customer_detail_page(
    request: Request,
    user_id: int,
    admin: Admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Mijoz topilmadi.")
    if not can_see_everything(admin) and user.assigned_admin_id not in (None, admin.id):
        raise HTTPException(status_code=404, detail="Mijoz topilmadi.")
    cases = await cases_for_user(db, user_id)
    return templates.TemplateResponse(request, "customer_detail.html", {"user": user, "cases": cases})
