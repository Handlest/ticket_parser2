# Базовый образ Playwright уже содержит браузеры и системные зависимости,
# поэтому отдельный `playwright install` не нужен.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

# Сначала зависимости — для кэширования слоёв при сборке.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Затем исходники и конфиг.
COPY app ./app
COPY setup.yaml ./setup.yaml

# Каталог для файла SQLite (монтируется как volume в docker-compose).
RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

CMD ["python", "-m", "app.main"]
