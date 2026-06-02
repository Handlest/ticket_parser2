"""Хендлеры Telegram-бота (aiogram 3).

Зависимости (repository, config) внедряются через workflow_data диспетчера —
они приходят в хендлеры как именованные аргументы (см. app/main.py).
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import AppConfig
from app.bot.keyboards import (
    BENEFIT_CALLBACK_PREFIX,
    benefit_keyboard,
    delete_keyboard,
)
from app.bot.states import AddTracking
from app.db.repository import TrackingRepository
from app.domain.benefits import BenefitCategory
from app.providers import CityResolver, LocationServiceError, ResolveResult

logger = logging.getLogger(__name__)
router = Router()

_DATE_FORMATS = ("%d.%m.%Y", "%Y-%m-%d")

SERVICE_UNAVAILABLE_TEXT = (
    "⚠️ Справочник городов S7 сейчас недоступен (сайт временно блокирует "
    "автоматические запросы). Попробуй ещё раз через минуту."
)

WELCOME_TEXT = (
    "🛫 <b>Привет! Я слежу за ценами на авиабилеты.</b>\n\n"
    "Ты добавляешь маршрут, дату и желаемую цену — а я регулярно проверяю билеты "
    "и присылаю уведомление, как только появится вариант дешевле твоего порога.\n\n"
    "Города пиши обычными словами (например, «Москва») — коды аэропортов я "
    "определю сам.\n\n"
    "Чтобы начать, отправь /add. Полный список команд — /help."
)

HELP_TEXT = (
    "🛫 <b>Бот отслеживания авиабилетов</b>\n\n"
    "Я слежу за ценами на билеты и пришлю уведомление, когда найдётся билет "
    "дешевле заданного порога.\n\n"
    "<b>Команды:</b>\n"
    "/add — добавить отслеживание\n"
    "/list — мои отслеживания (с кнопкой удаления)\n"
    "/cancel — отменить текущий ввод\n"
    "/help — эта справка"
)


def _resolved_text(label: str, result: ResolveResult) -> str:
    """Строка-подтверждение распознанного города (+ уведомление о новом коде)."""
    text = f"{label}: <b>{result.title}</b> ({result.iata})"
    if result.is_new:
        text += (
            f"\n➕ Добавлен новый IATA-код для города «{result.title}» — "
            f"{result.iata}."
        )
    return text


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(WELCOME_TEXT)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Сейчас нечего отменять.")
        return
    await state.clear()
    await message.answer("Ввод отменён.")


# --------------------------- Добавление (/add) ----------------------------


@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext) -> None:
    await state.set_state(AddTracking.origin)
    await message.answer("Откуда летим? Напиши город отправления, например: Москва.")


@router.message(AddTracking.origin, F.text)
async def add_origin(
    message: Message, state: FSMContext, resolver: CityResolver
) -> None:
    raw = message.text.strip()
    try:
        result = await resolver.resolve(raw)
    except LocationServiceError:
        await message.answer(SERVICE_UNAVAILABLE_TEXT)
        return
    if result is None:
        await message.answer(
            "Не нашёл такой город. Проверь название и попробуй ещё раз "
            "(например: Москва, Сочи, Владивосток)."
        )
        return
    await state.update_data(origin=raw)
    await state.set_state(AddTracking.destination)
    await message.answer(_resolved_text("Откуда", result))
    await message.answer("Куда летим? Напиши город назначения, например: Сочи.")


@router.message(AddTracking.destination, F.text)
async def add_destination(
    message: Message, state: FSMContext, resolver: CityResolver
) -> None:
    raw = message.text.strip()
    try:
        result = await resolver.resolve(raw)
    except LocationServiceError:
        await message.answer(SERVICE_UNAVAILABLE_TEXT)
        return
    if result is None:
        await message.answer(
            "Не нашёл такой город. Проверь название и попробуй ещё раз."
        )
        return
    await state.update_data(destination=raw)
    await state.set_state(AddTracking.departure_date)
    await message.answer(_resolved_text("Куда", result))
    await message.answer("На какую дату? Формат ДД.ММ.ГГГГ (например: 15.07.2026).")


@router.message(AddTracking.departure_date, F.text)
async def add_date(message: Message, state: FSMContext) -> None:
    parsed = _parse_date(message.text.strip())
    if parsed is None:
        await message.answer("Не понял дату. Формат: ДД.ММ.ГГГГ, например 15.07.2026.")
        return
    if parsed < date.today():
        await message.answer("Дата уже прошла. Укажи будущую дату.")
        return
    await state.update_data(departure_date=parsed.isoformat())
    await state.set_state(AddTracking.max_price)
    await message.answer("Какая максимальная цена (в рублях)? Например: 12000.")


@router.message(AddTracking.max_price, F.text)
async def add_price(message: Message, state: FSMContext) -> None:
    price = _parse_price(message.text.strip())
    if price is None or price <= 0:
        await message.answer("Нужно положительное число, например 12000.")
        return
    await state.update_data(max_price=price)
    await state.set_state(AddTracking.benefit)
    await message.answer("Выбери категорию льготы:", reply_markup=benefit_keyboard())


@router.callback_query(AddTracking.benefit, F.data.startswith(f"{BENEFIT_CALLBACK_PREFIX}:"))
async def add_benefit(
    callback: CallbackQuery, state: FSMContext, config: AppConfig
) -> None:
    value = callback.data.split(":", 1)[1]
    try:
        benefit = BenefitCategory(value)
    except ValueError:
        await callback.answer("Неизвестная льгота", show_alert=True)
        return

    await state.update_data(benefit=benefit.value)
    await state.set_state(AddTracking.interval)
    await callback.message.edit_text(f"Льгота: {benefit.label}")
    min_interval = config.scheduler.min_interval_minutes
    default_interval = config.scheduler.default_check_interval_minutes
    await callback.message.answer(
        f"Как часто проверять (в минутах)? Минимум {min_interval}, "
        f"рекомендую {default_interval}."
    )
    await callback.answer()


@router.message(AddTracking.interval, F.text)
async def add_interval(
    message: Message,
    state: FSMContext,
    repository: TrackingRepository,
    config: AppConfig,
) -> None:
    interval = _parse_int(message.text.strip())
    min_interval = config.scheduler.min_interval_minutes
    if interval is None or interval < min_interval:
        await message.answer(f"Нужно целое число не меньше {min_interval}.")
        return

    data = await state.get_data()
    await state.clear()

    tracking = await repository.add(
        user_id=message.from_user.id,
        origin=data["origin"],
        destination=data["destination"],
        departure_date=date.fromisoformat(data["departure_date"]),
        max_price=data["max_price"],
        benefit=BenefitCategory(data["benefit"]),
        check_interval_minutes=interval,
        currency=config.locale.currency,
    )

    await message.answer(
        "✅ Отслеживание добавлено:\n"
        f"{tracking.route_label()}\n"
        f"Дата: {tracking.departure_date:%d.%m.%Y}\n"
        f"Цена ниже: {tracking.max_price:.0f} {tracking.currency}\n"
        f"Льгота: {tracking.benefit_category.label}\n"
        f"Проверка каждые {tracking.check_interval_minutes} мин.\n\n"
        "Я пришлю уведомление, как только найду подходящий билет."
    )


# ------------------------------ Список (/list) -----------------------------


@router.message(Command("list"))
async def cmd_list(message: Message, repository: TrackingRepository) -> None:
    trackings = await repository.list_by_user(message.from_user.id)
    if not trackings:
        await message.answer("У тебя нет активных отслеживаний. Добавь через /add.")
        return

    await message.answer(f"Твои отслеживания ({len(trackings)}):")
    for t in trackings:
        text = (
            f"<b>#{t.id}</b> {t.route_label()}\n"
            f"Дата: {t.departure_date:%d.%m.%Y}\n"
            f"Цена ниже: {t.max_price:.0f} {t.currency}\n"
            f"Льгота: {t.benefit_category.label}\n"
            f"Интервал: {t.check_interval_minutes} мин."
        )
        await message.answer(text, reply_markup=delete_keyboard(t.id))


@router.callback_query(F.data.startswith("delete:"))
async def delete_tracking(
    callback: CallbackQuery, repository: TrackingRepository
) -> None:
    tracking_id = int(callback.data.split(":", 1)[1])
    deleted = await repository.delete(tracking_id, callback.from_user.id)
    if deleted:
        await callback.message.edit_text(f"🗑 Отслеживание #{tracking_id} удалено.")
        await callback.answer("Удалено")
    else:
        await callback.answer("Не найдено", show_alert=True)


# ------------------------------- Парсеры -----------------------------------


def _parse_date(text: str) -> date | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_price(text: str) -> float | None:
    cleaned = text.replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_int(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None
