# Создание Telegram-бота и установка токена

Создание самого бота остаётся за тобой. Шаги:

## 1. Создать бота через @BotFather

1. Открой в Telegram чат с [@BotFather](https://t.me/BotFather).
2. Отправь команду `/newbot`.
3. Укажи имя бота (отображаемое) — например, `My Flight Tracker`.
4. Укажи username бота — он должен заканчиваться на `bot`
   (например, `my_flight_tracker_bot`).
5. BotFather пришлёт **токен** вида:
   ```
   123456789:AAExampleTokenReplaceMeWithRealOne
   ```
   Это и есть `TELEGRAM_BOT_TOKEN`.

## 2. Куда вставить токен

Токен НЕ хранится в коде и НЕ коммитится. Он берётся из файла `.env`:

1. Скопируй шаблон:
   ```bash
   cp .env.example .env
   ```
2. Открой `.env` и вставь токен:
   ```
   TELEGRAM_BOT_TOKEN=123456789:твой_реальный_токен
   ```

В `setup.yaml` токен уже подставляется автоматически из этой переменной:
```yaml
telegram:
  token: "${TELEGRAM_BOT_TOKEN}"
```

## 3. (Опционально) Ограничить доступ к боту

Чтобы ботом могли пользоваться только конкретные люди, добавь их Telegram
`user_id` в `setup.yaml`:
```yaml
telegram:
  allowed_user_ids: [123456789, 987654321]
```
Узнать свой `user_id` можно у бота [@userinfobot](https://t.me/userinfobot).
Пустой список = доступ открыт всем.

## 4. Запуск

```bash
docker compose up -d
```
Затем открой своего бота в Telegram и отправь `/start`.
