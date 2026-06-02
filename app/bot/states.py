"""FSM-состояния пошагового добавления отслеживания (команда /add)."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AddTracking(StatesGroup):
    origin = State()
    destination = State()
    departure_date = State()
    max_price = State()
    benefit = State()
    interval = State()
