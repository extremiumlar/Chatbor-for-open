"""Ko'p admin-akkauntli Telethon menejeri — TZ v2 4-bo'lim (B-1).

Bitta jarayon ichida N ta `TelegramClient` (har biri bitta adminning shaxsiy
akkaunti). Har klient `admin_id` bilan bog'langan — shu orqali har hodisada
"qaysi admin" savoli avtomatik hal bo'ladi (TZ v2 4.2).

Salomatlik (TZ v2 4.3): sessiya uzilsa/bekor qilinsa admin mijozlari JIMGINA
yo'qoladi — bu eng xavfli rejim. Shuning uchun davriy tekshiruv har holat
O'TISHINI (transition) bazaga yozadi va superadminga alert yuboradi.
"""

import asyncio
import datetime
import logging
import os
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy import select
from telethon import TelegramClient
from telethon.errors import AuthKeyUnregisteredError, SessionRevokedError, UnauthorizedError

from core.models import Admin, AdminSession, SessionStatus

log = logging.getLogger("multi_client")

# wire_handlers(client, admin) — manual_relay har klientga hodisa
# ishlovchilarini shu callback orqali o'rnatadi (admin konteksti bilan).
WireHandlers = Callable[[TelegramClient, Admin], None]
AlertSink = Callable[[str, bool], Awaitable[None]]


@dataclass
class ManagedClient:
    admin_id: int
    admin_name: str
    session_row_id: int
    client: TelegramClient
    # Oxirgi ma'lum holat — faqat O'TISH paytida alert berish uchun
    # (har 60 soniyada "hali ham uzilgan" deb spam qilmaslik).
    last_status: SessionStatus = SessionStatus.DISCONNECTED


class MultiClientManager:
    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager],
        api_id: int,
        api_hash: str,
        sessions_dir: str,
        alert_sink: AlertSink,
        health_poll_seconds: float = 60.0,
    ) -> None:
        self.session_factory = session_factory
        self.api_id = api_id
        self.api_hash = api_hash
        self.sessions_dir = sessions_dir
        self.alert_sink = alert_sink
        self.health_poll_seconds = health_poll_seconds
        self.clients: dict[int, ManagedClient] = {}  # admin_id -> ManagedClient

    # ------------------------------------------------------------------ #
    # Ishga tushirish / to'xtatish
    # ------------------------------------------------------------------ #

    async def start_all(self, wire_handlers: WireHandlers) -> int:
        """Barcha faol adminlarning sessiyalarini ko'taradi.

        Qaytaradi: muvaffaqiyatli ulangan klientlar soni. Nofaol admin
        (TZ v2 4.2b) va avtorizatsiyasi yo'qolgan sessiya o'tkazib yuboriladi
        (ikkinchisi alert bilan).
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(AdminSession, Admin)
                .join(Admin, AdminSession.admin_id == Admin.id)
                .where(Admin.is_active.is_(True))
            )
            rows = result.all()

        os.makedirs(self.sessions_dir, exist_ok=True)

        if not rows:
            await self.alert_sink(
                "⚠️ Birorta ham faol admin sessiyasi topilmadi — "
                "scripts/add_admin_session.py bilan qo'shing.",
                True,
            )
            return 0

        connected = 0
        for session_row, admin in rows:
            ok = await self._start_one(session_row, admin, wire_handlers)
            if ok:
                connected += 1
        return connected

    async def _start_one(
        self, session_row: AdminSession, admin: Admin, wire_handlers: WireHandlers
    ) -> bool:
        path = os.path.join(self.sessions_dir, session_row.session_name)
        client = TelegramClient(path, self.api_id, self.api_hash)
        # TZ v2 4.4 — flood himoyasi: Telegram "kutib turing" desa (60
        # soniyagacha) Telethon o'zi uxlab qayta uradi; kattaroq kutishlar
        # xato sifatida ko'tariladi va tegishli joyda alert beriladi.
        client.flood_sleep_threshold = 60
        managed = ManagedClient(
            admin_id=admin.id,
            admin_name=admin.name,
            session_row_id=session_row.id,
            client=client,
        )
        try:
            await client.connect()
            if not await client.is_user_authorized():
                # Sessiya fayli bor, lekin avtorizatsiya bekor qilingan
                # (admin "Terminate all sessions" bosgan / parol o'zgargan).
                await client.disconnect()
                await self._set_status(
                    managed,
                    SessionStatus.AUTH_LOST,
                    error="Sessiya avtorizatsiyasi yo'qolgan — qayta login kerak.",
                )
                await self.alert_sink(
                    f"🔴 {admin.name} ({session_row.phone}) sessiyasi BEKOR QILINGAN — "
                    f"qayta login kerak (scripts/add_admin_session.py). "
                    f"Bu adminning mijozlari hozir kuzatilmayapti!",
                    True,
                )
                self.clients[admin.id] = managed
                return False
        except Exception as exc:
            await self._set_status(managed, SessionStatus.DISCONNECTED, error=repr(exc))
            await self.alert_sink(
                f"🔴 {admin.name} ({session_row.phone}) sessiyasiga ulanib bo'lmadi: {exc!r}",
                True,
            )
            self.clients[admin.id] = managed
            return False

        wire_handlers(client, admin)
        await self._set_status(managed, SessionStatus.CONNECTED, error=None)
        self.clients[admin.id] = managed
        log.info(
            "Admin '%s' (id=%s) sessiyasi ulandi: %s.",
            admin.name,
            admin.id,
            session_row.session_name,
        )
        return True

    async def stop_all(self) -> None:
        for managed in self.clients.values():
            if managed.client.is_connected():
                await managed.client.disconnect()

    # ------------------------------------------------------------------ #
    # Salomatlik kuzatuvi (TZ v2 4.3)
    # ------------------------------------------------------------------ #

    async def health_loop(self) -> None:
        """Fon vazifasi: har klient holatini davriy tekshiradi.

        Telethon uzilishlarda o'zi qayta ulanadi — bu kuzatuv "o'zi tuzalmagan"
        holatlarni (avtorizatsiya bekor, uzoq uzilish) sezib alert beradi.
        """
        while True:
            await asyncio.sleep(self.health_poll_seconds)
            for managed in self.clients.values():
                try:
                    await self._check_one(managed)
                except Exception:
                    log.exception(
                        "Sessiya salomatligini tekshirishda xato (admin_id=%s)",
                        managed.admin_id,
                    )

    async def _check_one(self, managed: ManagedClient) -> None:
        client = managed.client

        if not client.is_connected():
            if managed.last_status == SessionStatus.CONNECTED:
                await self._set_status(
                    managed, SessionStatus.DISCONNECTED, error="Ulanish uzilgan."
                )
                await self.alert_sink(
                    f"🟡 {managed.admin_name} sessiyasi uzildi — Telethon qayta "
                    f"ulanishga urinmoqda.",
                    True,
                )
            return

        try:
            # Yengil so'rov — avtorizatsiya hali amaldami tekshiradi.
            await managed.client.get_me()
        except (AuthKeyUnregisteredError, SessionRevokedError, UnauthorizedError) as exc:
            if managed.last_status != SessionStatus.AUTH_LOST:
                await self._set_status(managed, SessionStatus.AUTH_LOST, error=repr(exc))
                await self.alert_sink(
                    f"🔴 {managed.admin_name} sessiyasi BEKOR QILINGAN ({exc.__class__.__name__}) — "
                    f"qayta login kerak. Bu adminning mijozlari hozir kuzatilmayapti!",
                    True,
                )
            return
        except Exception:
            return  # vaqtinchalik tarmoq xatosi — keyingi aylanishda qayta

        if managed.last_status != SessionStatus.CONNECTED:
            await self._set_status(managed, SessionStatus.CONNECTED, error=None)
            await self.alert_sink(
                f"🟢 {managed.admin_name} sessiyasi qayta tiklandi.", False
            )
        else:
            # Holat o'zgarmagan — faqat last_seen_at yangilanadi.
            await self._touch_last_seen(managed)

    # ------------------------------------------------------------------ #
    # DB yozuvlari
    # ------------------------------------------------------------------ #

    async def _set_status(
        self, managed: ManagedClient, status: SessionStatus, error: str | None
    ) -> None:
        managed.last_status = status
        async with self.session_factory() as session:
            row = await session.get(AdminSession, managed.session_row_id)
            if row is None:
                return
            row.status = status
            row.last_error = error
            if status == SessionStatus.CONNECTED:
                row.last_seen_at = datetime.datetime.utcnow()
            await session.commit()

    async def _touch_last_seen(self, managed: ManagedClient) -> None:
        async with self.session_factory() as session:
            row = await session.get(AdminSession, managed.session_row_id)
            if row is None:
                return
            row.last_seen_at = datetime.datetime.utcnow()
            await session.commit()
