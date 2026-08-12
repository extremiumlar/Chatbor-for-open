"""Yangi admin akkauntini tizimga ulash — TZ v2 4.2a (B-1).

Superadmin serverda o'zi ishga tushiradi (adminbot orqali kod kiritish
oqimi YO'Q — TZ v2 4.2a):

    python -m scripts.add_admin_session

Skript:
1. Telefon raqamni so'raydi, Telegramga kelgan kodni va (bo'lsa) 2FA parolni
   interaktiv qabul qiladi.
2. `sessions/admin_<id>.session` faylini yaratadi (papka huquqi 700 —
   TZ v2 13.4).
3. `admins` jadvalida yozuv topadi/yaratadi va `admin_sessions`ga bog'laydi.

Bir akkauntni qayta ulash (sessiya bekor qilinganda) ham shu skript bilan:
mavjud yozuv topilsa, sessiya fayli yangilanadi, jadval qayta yozilmaydi.
"""

import asyncio
import os
import stat
import sys

# `python scripts/add_admin_session.py` ko'rinishida ham ishlashi uchun.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402
from telethon import TelegramClient  # noqa: E402

from core.config import settings  # noqa: E402
from core.db import get_session, init_db  # noqa: E402
from core.models import Admin, AdminRole, AdminSession, SessionStatus  # noqa: E402


def _ensure_sessions_dir() -> str:
    path = settings.sessions_dir
    os.makedirs(path, exist_ok=True)
    # TZ v2 13.4 — sessiya fayllari faqat xizmat foydalanuvchisiga ochiq.
    # Windows'da chmod cheklangan ta'sirga ega — POSIX serverda to'liq ishlaydi.
    try:
        os.chmod(path, stat.S_IRWXU)
    except OSError:
        pass
    return path


async def main() -> None:
    if not settings.api_id or not settings.api_hash:
        raise SystemExit(
            ".env faylida API_ID va API_HASH to'ldirilmagan!\n"
            "Ularni https://my.telegram.org -> API development tools dan oling."
        )

    await init_db()
    sessions_dir = _ensure_sessions_dir()

    print("=== Yangi admin sessiyasini ulash (TZ v2 4.2a) ===\n")
    name = input("Admin ismi (ro'yxatda ko'rinadigan): ").strip()
    if not name:
        raise SystemExit("Ism bo'sh bo'lishi mumkin emas.")

    # Telethon .start() telefon/kod/parolni o'zi interaktiv so'raydi.
    temp_session_path = os.path.join(sessions_dir, "_pending_login")
    client = TelegramClient(temp_session_path, settings.api_id, settings.api_hash)
    await client.start()

    me = await client.get_me()
    phone = f"+{me.phone}" if me.phone else "?"
    print("\nUlanish muvaffaqiyatli!")
    print(f"Ism:      {me.first_name} {me.last_name or ''}".strip())
    print(f"Username: @{me.username}" if me.username else "Username: yo'q")
    print(f"ID:       {me.id}")
    print(f"Telefon:  {phone}")
    await client.disconnect()

    async with get_session() as session:
        # Admin yozuvi: tg_user_id bo'yicha topiladi yoki yaratiladi.
        result = await session.execute(select(Admin).where(Admin.tg_user_id == me.id))
        admin = result.scalars().first()
        if admin is None:
            admin = Admin(tg_user_id=me.id, name=name, role=AdminRole.ADMIN)
            session.add(admin)
            await session.commit()
            await session.refresh(admin)
            print(f"\nYangi admin yozuvi yaratildi (id={admin.id}, rol=ADMIN).")
        else:
            print(f"\nMavjud admin topildi (id={admin.id}, rol={admin.role.value}).")

        session_name = f"admin_{admin.id}"
        final_path = os.path.join(sessions_dir, f"{session_name}.session")

        # _pending_login.session -> admin_<id>.session
        os.replace(f"{temp_session_path}.session", final_path)
        try:
            os.chmod(final_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

        result = await session.execute(
            select(AdminSession).where(AdminSession.admin_id == admin.id)
        )
        row = result.scalars().first()
        if row is None:
            session.add(
                AdminSession(
                    admin_id=admin.id,
                    session_name=session_name,
                    phone=phone,
                    status=SessionStatus.DISCONNECTED,
                )
            )
            print(f"admin_sessions yozuvi yaratildi: {session_name}.")
        else:
            # Qayta login (sessiya bekor qilingan edi) — yozuv yangilanadi.
            row.session_name = session_name
            row.phone = phone
            row.status = SessionStatus.DISCONNECTED
            row.last_error = None
            print(f"admin_sessions yozuvi yangilandi: {session_name} (qayta login).")
        await session.commit()

    print(f"\nSessiya fayli: {final_path}")
    print("Teleton (manual_relay) qayta ishga tushirilganda klient avtomatik ulanadi.")


if __name__ == "__main__":
    asyncio.run(main())
