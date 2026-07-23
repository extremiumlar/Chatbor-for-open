"""Strukturali log fayllar — TZ 12.1 (tizim xatoliklari doim log faylga
yoziladi, kritik xatoliklarda qo'shimcha adminbotga push — bu qism
`core.logic.notifier`/`case_manager._alert` orqali allaqachon ishlaydi)."""

import logging
import os
from logging.handlers import RotatingFileHandler

from core.config import settings

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def configure_logging(service_name: str) -> None:
    os.makedirs(settings.log_dir, exist_ok=True)
    log_path = os.path.join(settings.log_dir, f"{service_name}.log")

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Har ehtimolga qarshi — qayta chaqirilsa eski handler'lar takrorlanmasin.
    root.handlers.clear()

    formatter = logging.Formatter(_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
