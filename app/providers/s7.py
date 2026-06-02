"""Провайдер S7 Airlines (Playwright).

Результаты поиска S7 живут в отдельном React-движке ibe.s7.ru/air. Туда можно
зайти по deeplink (S7 сам создаёт сессию из параметров URL), не «прокликивая»
форму на www.s7.ru — это надёжнее. Затем со страницы снимаются офферы.

Особенности живого сайта (проверено вручную, см. docs/providers.md):
  * Страница — SPA, CSS-классы имеют хеш сборки (меняются при деплое), поэтому
    парсинг идёт по СТАБИЛЬНЫМ data-qa-атрибутам, а не по классам.
  * На странице может быть несколько рейсов (data-qa="tripToBlock"), в каждом —
    несколько тарифов (data-qa="tariffItemHeader"). Берём все.
  * Переключатель льгот ЗАВИСИТ ОТ МАРШРУТА: на одних маршрутах это одиночный
    чекбокс, на других (например, ДВ-направления) — выпадающий список
    «Выбрать категорию» с тумблерами «Для молодёжи и пенсионеров» и «Для жителей
    Дальнего Востока». Код устойчив к обоим вариантам: ищет тумблер по подписи,
    при необходимости предварительно открывает выпадающий список.
  * Если нужная льгота на маршруте недоступна — возвращаем пустой результат
    (ядро это переживёт, см. BaseProvider.safe_search).

Любой сбой не пробрасывается наружу — ядро вызывает safe_search().
"""

from __future__ import annotations

import logging
from datetime import date
from urllib.parse import urlencode

from app.domain.benefits import BenefitCategory
from app.providers.base import BaseProvider
from app.providers.models import FlightOffer, SearchQuery
from app.providers.registry import register

logger = logging.getLogger(__name__)

# JS-функция, которую исполняем на странице результатов: собирает офферы по
# стабильным data-qa-атрибутам и возвращает список словарей.
_EXTRACT_JS = r"""
() => {
  const toInt = (s) => {
    const d = (s || '').replace(/[^\d]/g, '');
    return d ? parseInt(d, 10) : null;
  };
  const blocks = Array.from(document.querySelectorAll('[data-qa="tripToBlock"]'));
  const result = [];
  for (const block of blocks) {
    const seg = block.querySelector('[data-qa="description_segmentItem"]');
    const segText = seg ? seg.innerText.replace(/\s+/g, ' ').trim() : '';
    const fnMatch = segText.match(/S7\s?\d{3,4}/);
    const flight = fnMatch ? fnMatch[0].replace(/\s+/g, ' ') : null;
    const timeMatch = segText.match(/\d{1,2}:\d{2}/g);
    const times = timeMatch ? timeMatch.slice(0, 2).join('–') : null;

    const tariffs = Array.from(
      block.querySelectorAll('[data-qa="tariffItemHeader"]')
    );
    for (const t of tariffs) {
      const nameEl = t.querySelector('[data-qa="name_tariffItem"]');
      const fare = nameEl ? nameEl.innerText.trim() : null;
      const priceMatch = t.innerText.match(/(\d[\d\s\u00a0]*)\s*₽/);
      const price = priceMatch ? toInt(priceMatch[1]) : null;
      if (price) {
        result.push({ fare, price, flight, times });
      }
    }
  }
  return result;
}
"""

# JS для включения тумблера льготы. Принимает подстроку подписи тумблера.
# Возвращает статус: 'clicked' | 'already_on' | 'opened_dropdown' | 'not_found'.
_TOGGLE_JS = r"""
(needle) => {
  const lower = needle.toLowerCase();
  const findToggle = () => {
    const titles = Array.from(
      document.querySelectorAll('div, span, label')
    ).filter(
      (e) =>
        e.children.length <= 2 &&
        e.textContent.trim().toLowerCase().includes(lower)
    );
    for (const title of titles) {
      let node = title;
      for (let i = 0; i < 5 && node; i++) {
        const input = node.querySelector
          ? node.querySelector('input[type="checkbox"], [role="switch"]')
          : null;
        if (input) return input;
        node = node.parentElement;
      }
    }
    return null;
  };

  let input = findToggle();
  if (!input) {
    // Возможно, тумблеры спрятаны в выпадающем списке «Выбрать категорию».
    const dd = Array.from(
      document.querySelectorAll('button, [role="button"]')
    ).find((e) => /выбрать категорию/i.test(e.textContent));
    if (dd) {
      dd.click();
      return 'opened_dropdown';
    }
    return 'not_found';
  }
  const isOn =
    input.checked || input.getAttribute('aria-checked') === 'true';
  if (isOn) return 'already_on';
  input.click();
  return 'clicked';
}
"""


@register
class S7Provider(BaseProvider):
    name = "s7"
    display_name = "S7 Airlines"

    IBE_URL = "https://ibe.s7.ru/air"

    # Подстрока подписи тумблера льготы на странице результатов.
    # youth и pensioner объединены S7 в один тумблер «Для молодёжи и пенсионеров».
    _BENEFIT_TOGGLE: dict[BenefitCategory, str] = {
        BenefitCategory.YOUTH: "молод",
        BenefitCategory.PENSIONER: "молод",
        BenefitCategory.FAR_EAST: "дальнего востока",
    }

    def supports_benefit(self, benefit: BenefitCategory) -> bool:
        # Онлайн S7 в этом потоке поддерживает обычные билеты, молодёжь/пенсионеров
        # и (на части маршрутов) жителей ДВ. Многодетные/инвалиды — не здесь.
        return benefit in {
            BenefitCategory.NONE,
            BenefitCategory.YOUTH,
            BenefitCategory.PENSIONER,
            BenefitCategory.FAR_EAST,
        }

    def build_url(self, origin_code: str, dest_code: str, departure: date) -> str:
        """Собирает deeplink в движок бронирования S7."""
        params = {
            "id": "deeplink",
            "journeySpan": "OW",  # one-way
            "DA1": origin_code,
            "AA1": dest_code,
            "DD1": departure.strftime("%Y-%m-%d"),
            "TA": 1,  # взрослых
            "TC": 0,  # детей
            "TI": 0,  # младенцев
            "CUR": "RUB",
            "LAN": "ru",
            "searchTypeRed": "portalAvia",
        }
        return f"{self.IBE_URL}?{urlencode(params)}"

    async def search(self, query: SearchQuery) -> list[FlightOffer]:
        if self.resolver is None:
            logger.error("S7: резолвер кодов не сконфигурирован — поиск невозможен")
            return []

        # Город → IATA-код. Обычно это кэш-попадание (код уже сохранён при /add).
        origin = await self.resolver.resolve(query.origin)
        dest = await self.resolver.resolve(query.destination)
        if origin is None or dest is None:
            logger.warning(
                "S7: не удалось определить IATA-код для '%s' -> '%s'",
                query.origin,
                query.destination,
            )
            return []
        origin_code, dest_code = origin.iata, dest.iata

        url = self.build_url(origin_code, dest_code, query.departure_date)
        timeout_ms = self.config.request_timeout_seconds * 1000

        # Ленивый импорт: без Playwright остальное приложение работает.
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self.config.headless)
            try:
                page = await browser.new_page()
                await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                # Ждём появления хотя бы одного блока рейса.
                try:
                    await page.wait_for_selector(
                        '[data-qa="tripToBlock"]', timeout=timeout_ms
                    )
                except Exception:
                    logger.info(
                        "S7: рейсы не появились (нет мест/маршрута?). URL: %s", url
                    )
                    return []

                if query.benefit is not BenefitCategory.NONE:
                    applied = await self._apply_benefit(page, query.benefit, timeout_ms)
                    if not applied:
                        logger.info(
                            "S7: льгота '%s' недоступна на маршруте %s-%s — пропуск",
                            query.benefit.value,
                            origin_code,
                            dest_code,
                        )
                        return []

                raw = await page.evaluate(_EXTRACT_JS)
                final_url = page.url
            finally:
                await browser.close()

        return self._to_offers(raw, query, final_url)

    async def _apply_benefit(
        self, page, benefit: BenefitCategory, timeout_ms: int
    ) -> bool:
        """Включает тумблер льготы. Устойчив к разной вёрстке на разных маршрутах.

        Возвращает True, если тумблер включён (или уже был включён), иначе False.
        """
        needle = self._BENEFIT_TOGGLE[benefit]
        # До двух попыток: первая может лишь открыть выпадающий список.
        for _ in range(2):
            status = await page.evaluate(_TOGGLE_JS, needle)
            if status in {"clicked", "already_on"}:
                if status == "clicked":
                    # Дать странице перерисовать тарифы под льготу.
                    try:
                        await page.wait_for_load_state(
                            "networkidle", timeout=timeout_ms
                        )
                    except Exception:
                        await page.wait_for_timeout(1500)
                return True
            if status == "opened_dropdown":
                await page.wait_for_timeout(500)
                continue
            # 'not_found'
            return False
        return False

    def _to_offers(
        self, raw: list[dict], query: SearchQuery, url: str
    ) -> list[FlightOffer]:
        offers: list[FlightOffer] = []
        for item in raw:
            price = item.get("price")
            if not price:
                continue
            details_parts = [p for p in (item.get("flight"), item.get("fare")) if p]
            offers.append(
                FlightOffer(
                    provider=self.name,
                    origin=query.origin,
                    destination=query.destination,
                    departure_date=query.departure_date,
                    price=float(price),
                    currency=query.currency,
                    url=url,
                    airline=self.display_name,
                    details=" · ".join(details_parts) or None,
                )
            )

        if not offers:
            logger.info("S7: офферы не распознаны на странице. URL: %s", url)
        return offers
