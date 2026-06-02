"""Пример провайдера на основе HTTP-запросов (httpx).

RedWing (Red Wings) демонстрирует «лёгкий» провайдер: если у сайта есть открытый
JSON-API или статичный HTML, браузер не нужен — это быстрее и экономит ресурсы.
Эндпоинт/формат ответа здесь — шаблонные и помечены TODO: их нужно подставить
под реальный сайт. Любой сбой не пробрасывается наружу (см. safe_search).

Как адаптировать — см. docs/providers.md.
"""

from __future__ import annotations

import logging

import httpx

from app.providers.base import BaseProvider
from app.providers.models import FlightOffer, SearchQuery
from app.providers.registry import register

logger = logging.getLogger(__name__)


@register
class RedWingProvider(BaseProvider):
    name = "redwing"
    display_name = "Red Wings"

    BASE_URL = "https://www.flyredwings.com"
    # TODO: указать реальный эндпоинт поиска (если есть открытый API).
    SEARCH_ENDPOINT = "/api/search"

    def build_params(self, query: SearchQuery) -> dict[str, str]:
        return {
            "origin": query.origin,
            "destination": query.destination,
            "date": query.departure_date.strftime("%Y-%m-%d"),
            "currency": query.currency,
        }

    def build_url(self, query: SearchQuery) -> str:
        """Ссылка на страницу с результатами для пользователя (в уведомлении)."""
        params = self.build_params(query)
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.BASE_URL}/search?{query_string}"

    async def search(self, query: SearchQuery) -> list[FlightOffer]:
        timeout = self.config.request_timeout_seconds
        async with httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PlaneTicketBot)"},
        ) as client:
            response = await client.get(
                self.SEARCH_ENDPOINT, params=self.build_params(query)
            )
            response.raise_for_status()
            data = response.json()

        return self._parse(data, query)

    def _parse(self, data: dict, query: SearchQuery) -> list[FlightOffer]:
        """Преобразует JSON-ответ в офферы.

        TODO: подставить реальную структуру ответа. Сейчас при незнакомом формате
        метод корректно возвращает пустой список.
        """
        offers: list[FlightOffer] = []
        url = self.build_url(query)

        # TODO: заменить "flights"/"price" на реальные ключи ответа API.
        for item in data.get("flights", []):
            price = item.get("price")
            if price is None:
                continue
            offers.append(
                FlightOffer(
                    provider=self.name,
                    origin=query.origin,
                    destination=query.destination,
                    departure_date=query.departure_date,
                    price=float(price),
                    currency=query.currency,
                    url=item.get("url", url),
                    airline=self.display_name,
                    details=item.get("flight_number"),
                )
            )

        if not offers:
            logger.info(
                "RedWing: офферы не найдены/не распознаны (нужна донастройка "
                "под реальный API)."
            )
        return offers
