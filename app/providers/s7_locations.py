"""Резолвер «город → IATA-код» поверх публичного location-сервиса S7.

Пользователь не обязан знать IATA-коды: он пишет город по-русски, а код мы
достаём сами. Источник — тот же справочник, что питает автоподсказку на сайте
S7 (проверено вручную, см. docs/providers.md):

    GET https://www.s7.ru/S7WLocationService/location
        ?action=get_locations&searchType=avia&str=<город>&lang=ru&...

Ответ (сокращённо):
    {"stc":200,"c":[{"iata":"MOW","ibeCode":"MOW","type":"city",
                     "name":"Москва, (все аэропорты)", ...}]}

Среди кандидатов предпочитаем запись type="city" — это агрегатный код города
(например MOW = все аэропорты Москвы). Он работает в deeplink, поэтому один
поиск покрывает сразу все аэропорты города и перебор комбинаций не нужен.

Найденный код кэшируется в БД (таблица airports) навсегда: IATA-коды стабильны.
Поэтому к сайту обращаемся только при первой встрече нового города.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.db.repository import AirportRepository

logger = logging.getLogger(__name__)

_LOCATION_URL = "https://www.s7.ru/S7WLocationService/location"
_SITE_URL = "https://www.s7.ru/"
# S7 за антиботом (Qrator) — отправляем «браузерный» User-Agent.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class LocationServiceError(Exception):
    """Справочник S7 недоступен (антибот/сеть), а не «город не найден»."""


@dataclass(slots=True)
class ResolveResult:
    iata: str
    title: str  # человекочитаемое название из селектора S7
    is_new: bool  # True, если код только что сохранён в БД (раньше не встречался)


class CityResolver:
    """Преобразует ввод пользователя в IATA-код с кэшированием в БД."""

    def __init__(
        self,
        airports: AirportRepository,
        timeout_seconds: int = 30,
        headless: bool = True,
    ) -> None:
        self._airports = airports
        self._timeout = timeout_seconds
        self._headless = headless

    async def resolve(self, raw: str) -> ResolveResult | None:
        """Возвращает IATA-код для города (или None, если не удалось определить)."""
        value = " ".join(raw.split())  # схлопываем пробелы
        if not value:
            return None

        # Готовый 3-буквенный код — используем как есть, в кэш не пишем.
        if len(value) == 3 and value.isalpha():
            return ResolveResult(iata=value.upper(), title=value.upper(), is_new=False)

        key = value.lower()
        cached = await self._airports.get(key)
        if cached is not None:
            return ResolveResult(iata=cached.iata, title=cached.title, is_new=False)

        found = await self._fetch(value)  # может бросить LocationServiceError
        if found is None:
            return None

        iata, title = found
        await self._airports.save(key, iata, title)
        logger.info("Новый IATA-код в кэше: '%s' -> %s (%s)", key, iata, title)
        return ResolveResult(iata=iata, title=title, is_new=True)

    async def _fetch(self, value: str) -> tuple[str, str] | None:
        """Запрашивает справочник S7 и выбирает лучший вариант для города.

        Сначала пробует лёгкий httpx. Если S7 режет запрос антиботом (Qrator
        отдаёт 503) — повторяет тот же запрос изнутри браузера (Playwright),
        который проходит проверку. Возвращает (iata, title) либо None, если
        город честно не найден. При полном отказе сервиса бросает
        LocationServiceError — чтобы отличить «недоступно» от «не найдено».
        """
        params = {
            "action": "get_locations",
            "searchType": "avia",
            "offset": 0,
            "limit": 30,
            "str": value,
            "lang": "ru",
            "withRailStations": "false",
        }

        data = await self._fetch_httpx(params)
        if data is None:
            logger.warning(
                "S7 location: httpx заблокирован для '%s', пробую Playwright", value
            )
            data = await self._fetch_browser(params)
        if data is None:
            raise LocationServiceError(value)

        return self._parse(value, data)

    async def _fetch_httpx(self, params: dict) -> dict | None:
        """Лёгкий запрос. Возвращает разобранный JSON или None при любом сбое."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(_LOCATION_URL, params=params, headers=_HEADERS)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001 — сбой переводит на фолбэк
            logger.info("S7 location: httpx-запрос не удался (%s)", exc)
            return None

    async def _fetch_browser(self, params: dict) -> dict | None:
        """Фолбэк: тот же эндпоинт из браузерной сессии (проходит Qrator).

        Заходим на www.s7.ru и ДАЁМ JS-challenge Qrator выполниться (он ставит
        cookie-допуск и перезагружает страницу) — для этого ждём networkidle.
        Только потом делаем fetch к location-сервису (same-origin, без CORS).
        Challenge может доустанавливать куки не мгновенно — поэтому до 3 попыток.
        """
        url = f"{_LOCATION_URL}?{urlencode(params)}"
        timeout_ms = self._timeout * 1000
        # Ленивый импорт: без Playwright остальное приложение работает.
        from playwright.async_api import async_playwright

        # Возвращаем структуру, чтобы в логах был виден статус браузерного fetch.
        fetch_js = """
        async (url) => {
          try {
            const r = await fetch(url, { headers: { Accept: 'application/json' } });
            if (!r.ok) return { ok: false, status: r.status };
            return { ok: true, data: await r.json() };
          } catch (e) {
            return { ok: false, status: 0, error: String(e) };
          }
        }
        """
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=self._headless)
                try:
                    context = await browser.new_context(
                        user_agent=_HEADERS["User-Agent"], locale="ru-RU"
                    )
                    page = await context.new_page()
                    # Прогрев сессии: даём Qrator отдать и пройти JS-challenge.
                    await page.goto(
                        _SITE_URL, timeout=timeout_ms, wait_until="domcontentloaded"
                    )
                    try:
                        await page.wait_for_load_state(
                            "networkidle", timeout=timeout_ms
                        )
                    except Exception:  # noqa: BLE001 — networkidle не критичен
                        pass

                    for attempt in range(3):
                        res = await page.evaluate(fetch_js, url)
                        if res.get("ok"):
                            return res.get("data")
                        logger.warning(
                            "S7 location: браузерный fetch не прошёл "
                            "(статус=%s, err=%s, попытка %d/3)",
                            res.get("status"),
                            res.get("error"),
                            attempt + 1,
                        )
                        await page.wait_for_timeout(1500)
                    return None
                finally:
                    await browser.close()
        except Exception:  # noqa: BLE001 — фолбэк тоже может упасть
            logger.exception("S7 location: Playwright-фолбэк не удался")
            return None

    @staticmethod
    def _parse(value: str, data: dict) -> tuple[str, str] | None:
        """Выбирает лучший вариант из ответа справочника."""
        candidates = data.get("c") or []
        if not candidates:
            return None

        # Предпочитаем агрегатную запись города; иначе берём первую подходящую.
        best = next((c for c in candidates if c.get("type") == "city"), candidates[0])
        iata = (best.get("ibeCode") or best.get("iata") or "").strip().upper()
        title = (best.get("name") or "").strip()
        if len(iata) != 3 or not iata.isalpha():
            logger.warning("S7 location: не разобрал код для '%s': %r", value, best)
            return None
        return iata, title or iata
