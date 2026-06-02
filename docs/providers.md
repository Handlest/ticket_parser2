# Провайдеры: как добавить новый сайт

Модульность — главный приоритет проекта. Ядро (`core/`) и бот (`bot/`) работают
только с нормализованными `SearchQuery` и `FlightOffer` и **ничего не знают** о
конкретных сайтах. Чтобы подключить новый сайт (например, Аэрофлот или «Уральские
авиалинии»), не нужно трогать ядро.

## Контракт провайдера

Каждый провайдер наследуется от `BaseProvider` (`app/providers/base.py`):

```python
class BaseProvider(ABC):
    name: str             # уникальное имя для setup.yaml (providers.enabled)
    display_name: str     # человекочитаемое название

    async def search(self, query: SearchQuery) -> list[FlightOffer]: ...
    def supports_benefit(self, benefit: BenefitCategory) -> bool: ...   # опц.
```

Ядро вызывает не `search()`, а `safe_search()` — обёртку, которая ловит любые
исключения и возвращает `[]`. Поэтому сбой одного провайдера не ломает остальные.
В `search()` можно спокойно бросать исключения при сетевых/парсинговых ошибках.

### Нормализованные модели (`app/providers/models.py`)

- **`SearchQuery`**: `origin`, `destination`, `departure_date`, `max_price`,
  `benefit`, `currency`.
- **`FlightOffer`**: `provider`, `origin`, `destination`, `departure_date`,
  `price`, `currency`, `url`, `airline` (опц.), `details` (опц.).

## Два типа провайдеров

В поставке есть по одному примеру каждого типа:

| Тип | Пример | Когда использовать |
|-----|--------|--------------------|
| Браузерный (Playwright) | `s7.py` | Сайт с тяжёлым JS, динамической подгрузкой, антиботом |
| HTTP (httpx) | `redwing.py` | Есть открытый JSON-API или статичный HTML |

Браузерный тяжелее по ресурсам, но переживает JS-сайты. HTTP-провайдер быстрее —
предпочитай его, если сайт это позволяет.

## Шаги добавления нового провайдера

1. **Создай файл** `app/providers/myairline.py`.
2. **Унаследуйся** от `BaseProvider`, задай `name` и `display_name`.
3. **Реализуй `search()`** — построй URL/запрос, получи данные, распарси в
   список `FlightOffer`.
4. **Зарегистрируй** класс декоратором `@register`.
5. **Добавь импорт** модуля в `app/providers/__init__.py` (чтобы сработала
   регистрация).
6. **Включи** провайдер в `setup.yaml`:
   ```yaml
   providers:
     enabled: [s7, redwing, myairline]
   ```

### Шаблон (HTTP-провайдер)

```python
import httpx
from app.providers.base import BaseProvider
from app.providers.models import FlightOffer, SearchQuery
from app.providers.registry import register


@register
class MyAirlineProvider(BaseProvider):
    name = "myairline"
    display_name = "My Airline"
    BASE_URL = "https://example-airline.com"

    async def search(self, query: SearchQuery) -> list[FlightOffer]:
        async with httpx.AsyncClient(
            base_url=self.BASE_URL, timeout=self.config.request_timeout_seconds
        ) as client:
            resp = await client.get("/api/search", params={
                "from": query.origin,
                "to": query.destination,
                "date": query.departure_date.isoformat(),
            })
            resp.raise_for_status()
            data = resp.json()

        return [
            FlightOffer(
                provider=self.name,
                origin=query.origin,
                destination=query.destination,
                departure_date=query.departure_date,
                price=float(item["price"]),
                currency=query.currency,
                url=item["url"],
                airline=self.display_name,
            )
            for item in data["flights"]
        ]
```

## S7 Airlines — как устроен живой провайдер

`s7.py` — рабочий браузерный провайдер, проверенный на живом сайте. Ключевые
решения (важны, если сайт изменится и парсер сломается):

- **Deeplink вместо «прокликивания» формы.** Результаты поиска живут в отдельном
  React-движке `ibe.s7.ru/air`. Туда можно зайти по deeplink с параметрами
  маршрута/даты — S7 сам создаёт сессию (`execution`, `ibe_conversation`, токены
  Spring WebFlow) из URL. Это надёжнее, чем заполнять форму на `www.s7.ru`.
  Сборка ссылки — в `build_url()` (`urlencode` параметров `DA1`/`AA1`/`DD1`/…).
- **Парсинг по `data-qa`, не по классам.** Это SPA, CSS-классы имеют хеш сборки
  и меняются при каждом деплое. Стабильны только `data-qa`-атрибуты. JS-извлечение
  (`_EXTRACT_JS`) идёт по цепочке: `[data-qa="tripToBlock"]` (блок рейса) →
  `[data-qa="description_segmentItem"]` (номер рейса по `/S7\s?\d{3,4}/`, время) →
  `[data-qa="tariffItemHeader"]` (тариф) → `[data-qa="name_tariffItem"]` (название
  тарифа) + цена по `/(\d[\d\s\u00a0]*)\s*₽/`. На странице может быть несколько
  рейсов и у каждого несколько тарифов — берём все.
- **IATA-коды резолвятся автоматически (см. ниже «Резолвер городов»).** Провайдер
  получает `CityResolver` и переводит города пользователя в коды. Обычно это
  кэш-попадание, т.к. код уже сохранён в момент `/add`. Если резолвер не передан
  или код не определён — провайдер возвращает `[]` и пишет в лог.
- **Переключатель льгот зависит от маршрута.** На одних маршрутах (напр. Сочи) это
  одиночный чекбокс «Для молодёжи и пенсионеров», на других (ДВ-направления, напр.
  Улан-Удэ) — выпадающий список «Выбрать категорию» с тумблерами. `_apply_benefit()`
  устойчив к обоим вариантам: `_TOGGLE_JS` ищет тумблер по подписи, а если не нашёл —
  кликает «Выбрать категорию» и пробует ещё раз (до 2 попыток). Если льгота на
  маршруте недоступна — возвращаем `[]` (ядро это переживёт).
- **Поддерживаемые льготы:** только `NONE`, `YOUTH`, `PENSIONER`, `FAR_EAST`.
  youth и pensioner объединены S7 в один тумблер. Многодетные/инвалиды в этом
  онлайн-потоке недоступны — `supports_benefit()` для них возвращает `False`.

## Резолвер городов «город → IATA-код» (`s7_locations.py`)

Пользователь не обязан знать коды аэропортов — он пишет город по-русски, а код
достаётся автоматически и кэшируется в БД навсегда.

- **Источник кодов** — публичный location-сервис S7, тот же, что питает
  автоподсказку на сайте (найден через DevTools → Network):
  ```
  GET https://www.s7.ru/S7WLocationService/location
      ?action=get_locations&searchType=avia&str=<город>&lang=ru&withRailStations=false
  ```
  Ответ: `{"stc":200,"c":[{"iata":"MOW","ibeCode":"MOW","type":"city",
  "name":"Москва, (все аэропорты)", ...}]}`. Это лёгкий JSON, поэтому резолвер
  работает на `httpx` (без браузера). Обращаемся к нему только при первой встрече
  нового города.
- **Агрегатный код города.** Среди кандидатов предпочитаем запись `type="city"` —
  это код всех аэропортов города (напр. `MOW` = SVO/DME/VKO). Он работает в
  deeplink (`AA1=MOW` проверено вживую), поэтому **один поиск покрывает все
  аэропорты** города, и перебирать комбинации аэропортов не нужно.
- **Кэш в БД.** Таблица `airports` (`query` → `iata`, `title`). `query` — это
  нормализованный (нижний регистр, схлопнутые пробелы) ввод пользователя. TTL
  нет: IATA-коды стабильны. Репозиторий — `AirportRepository` (`get`/`save`).
- **Где используется.** `CityResolver` создаётся в `app/main.py` и
  прокидывается: (1) в бот через DI — для мгновенного резолва при `/add` и
  ответа пользователю (а при первом сохранении кода — уведомления «Добавлен
  новый IATA-код…»); (2) в провайдеры через `build_enabled_providers(...)` — на
  этапе поиска (обычно кэш-попадание).
- **Готовый код.** Если пользователь всё же ввёл 3-буквенный код (`MOW`) — он
  принимается как есть, без запроса к сайту.
- **Антибот + фолбэк через браузер.** Сервис отдаётся за Qrator. Сначала идёт
  лёгкий `httpx`-запрос с «браузерным» User-Agent (`_fetch_httpx`). На сервере
  (датацентр-IP) Qrator может вернуть `503` — тогда `_fetch` автоматически
  повторяет тот же запрос изнутри Playwright (`_fetch_browser`): заходим на
  `www.s7.ru` (выставляются антибот-куки), затем `page.evaluate(fetch ...)` к
  location-сервису (same-origin, без CORS). Браузер проходит Qrator там, где
  голый httpx режется. Поднимать GUI не нужно — браузер работает в headless
  (параметр `providers.headless`), что и требуется на сервере.
- **«Не найден» vs «недоступен».** `resolve()` возвращает `None`, только если
  город честно не найден (`c: []`). Если же отказали оба пути (httpx + браузер),
  бросается `LocationServiceError` — бот показывает отдельное сообщение «справочник
  временно недоступен», а не «город не найден». В провайдерах исключение
  поглощается `BaseProvider.safe_search` (поиск просто вернёт `[]`).

## Донастройка HTTP-примера (`redwing.py`)

В `redwing.py` эндпоинт и ключи ответа помечены `TODO`. Во вкладке Network найди
запрос поиска, подставь реальный `SEARCH_ENDPOINT`, параметры (`build_params`) и
ключи ответа в `_parse()`.

## Учёт льгот

Если сайт умеет искать только обычные билеты — переопредели `supports_benefit()`,
чтобы провайдер пропускал запросы с неподдерживаемыми категориями (тогда он не
будет зря дёргать сайт). Если сайт поддерживает все категории — метод можно не
переопределять (по умолчанию возвращает `True`).
