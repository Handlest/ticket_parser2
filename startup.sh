#!/usr/bin/env bash
# Сборка и запуск бота в Docker без docker-compose.
# Эквивалент docker-compose.yml: тот же образ, volume'ы и .env.
# Запускать из корня проекта: ./startup.sh
set -euo pipefail

# Используем BuildKit-сборщик (убирает предупреждение про legacy builder).
export DOCKER_BUILDKIT=1

IMAGE="plane_ticket_bot"
CONTAINER="plane_ticket_bot"

# Переходим в каталог скрипта — пути ниже считаем от корня проекта.
cd "$(dirname "$0")"

# Проверяем, что .env на месте (из него берутся токен и список user_id).
if [[ ! -f .env ]]; then
  echo "Файл .env не найден. Скопируй .env.example в .env и заполни токен." >&2
  exit 1
fi

# Каталог для БД и логов (монтируется как volume).
mkdir -p data

echo "Сборка образа ${IMAGE}..."
docker build -t "${IMAGE}" .

# Останавливаем и удаляем прежний контейнер, если он есть.
if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER}"; then
  echo "Останавливаю прежний контейнер ${CONTAINER}..."
  docker rm -f "${CONTAINER}" >/dev/null
fi

echo "Запуск контейнера ${CONTAINER}..."
docker run -d \
  --name "${CONTAINER}" \
  --restart unless-stopped \
  --env-file .env \
  -v "$(pwd)/setup.yaml:/app/setup.yaml:ro" \
  -v "$(pwd)/data:/app/data" \
  "${IMAGE}"

echo "Готово. Логи: docker logs -f ${CONTAINER}"
