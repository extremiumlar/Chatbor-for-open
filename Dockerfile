FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Aniq buyruq docker-compose.yml'dagi `command:` orqali beriladi
# (teleton_service.relay yoki adminbot_service.bot) — TZ 13.1 mikroservis
# mantig'i, ikkovi bitta image, alohida jarayon sifatida ishlaydi.
CMD ["python", "-m", "teleton_service.relay"]
