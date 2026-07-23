"""Telegram akkauntga Telethon orqali birinchi marta ulanish (login).

Ishlatish:
    python login.py

Skript telefon raqam, Telegramga kelgan kod va (agar yoqilgan boʻlsa)
2FA parolni soʻraydi. Muvaffaqiyatli kirishdan keyin `my_account.session`
fayli yaratiladi — keyingi ulanishlar kod soʻramaydi.
"""

import os

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME", "my_account")

if not API_ID or not API_HASH:
    raise SystemExit(
        ".env faylida API_ID va API_HASH toʻldirilmagan!\n"
        "Ularni https://my.telegram.org -> API development tools dan oling."
    )


async def main():
    client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)
    await client.start()

    me = await client.get_me()
    print("\nUlanish muvaffaqiyatli!")
    print(f"Ism:      {me.first_name} {me.last_name or ''}".strip())
    print(f"Username: @{me.username}" if me.username else "Username: yoʻq")
    print(f"ID:       {me.id}")
    print(f"Telefon:  +{me.phone}")
    print(f"\nSessiya fayli: {SESSION_NAME}.session")

    await client.disconnect()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
