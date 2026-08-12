"""Chiquvchi rasmlarni partiyaga yig'ish — TZ v2 5.1 (B-2).

Ikki rejim:
- **Albom** (`grouped_id` bor) — Telegram bitta yuborishni bir nechta hodisa
  qilib beradi; qisqa "tinchlik" (debounce) bilan yig'iladi: har yangi rasm
  taymerni qayta boshlaydi, ~2 soniya jim bo'lgach partiya tayyor.
- **Yakka rasmlar** — birinchi rasmdan boshlab N soniyalik QAT'IY oyna
  (TZ: "shu vaqt ichida bitta mijozga ketgan hamma rasm bitta partiya");
  oyna yopilganda partiya tayyor.

Modul Telethon'ga bog'lanmagan (xabar obyekti har qanday narsa bo'lishi
mumkin) — sof asyncio, testlab bo'ladi.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

log = logging.getLogger("batch_collector")

# on_ready(chat_id, messages) — partiya tayyor bo'lganda chaqiriladi.
BatchReady = Callable[[int, list[Any]], Awaitable[None]]

_ALBUM_DEBOUNCE_SECONDS = 2.0


@dataclass
class _Pending:
    messages: list[Any] = field(default_factory=list)
    task: asyncio.Task | None = None


class BatchCollector:
    def __init__(self, on_ready: BatchReady, window_seconds: float = 15.0) -> None:
        self.on_ready = on_ready
        self.window_seconds = window_seconds
        # (chat_id, grouped_id | None) -> yig'ilayotgan partiya
        self._pending: dict[tuple[int, int | None], _Pending] = {}

    def add(self, chat_id: int, message: Any, grouped_id: int | None = None) -> None:
        """Yangi chiquvchi rasm keldi — mos partiyaga qo'shadi."""
        key = (chat_id, grouped_id)
        pending = self._pending.get(key)

        if pending is None:
            pending = _Pending()
            self._pending[key] = pending
            pending.messages.append(message)
            pending.task = asyncio.create_task(self._finalize_later(key, grouped_id))
            return

        pending.messages.append(message)
        if grouped_id is not None and pending.task is not None:
            # Albomda har yangi rasm debounce'ni qayta boshlaydi.
            pending.task.cancel()
            pending.task = asyncio.create_task(self._finalize_later(key, grouped_id))
        # Yakka-rasm oynasi esa QAT'IY: birinchi rasmdan boshlab o'lchanadi,
        # qayta boshlanmaydi — aks holda admin sekin tashlasa oyna cheksiz
        # cho'zilib ketardi.

    async def _finalize_later(self, key: tuple[int, int | None], grouped_id: int | None) -> None:
        try:
            delay = _ALBUM_DEBOUNCE_SECONDS if grouped_id is not None else self.window_seconds
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

        pending = self._pending.pop(key, None)
        if pending is None or not pending.messages:
            return
        try:
            await self.on_ready(key[0], pending.messages)
        except Exception:
            log.exception("Partiya ishlovida xato (chat_id=%s)", key[0])

    async def drain(self) -> None:
        """Testlar/to'xtash uchun: barcha kutayotgan partiyalarni darhol yopadi."""
        keys = list(self._pending.keys())
        for key in keys:
            pending = self._pending.pop(key, None)
            if pending is None:
                continue
            if pending.task is not None:
                pending.task.cancel()
            if pending.messages:
                try:
                    await self.on_ready(key[0], pending.messages)
                except Exception:
                    log.exception("Partiya ishlovida xato (chat_id=%s)", key[0])
