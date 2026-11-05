from aiogram.dispatcher.filters.state import State, StatesGroup


class LoginStates(StatesGroup):
    """Telegram akkauntni tizimga bog'lash: avval login, keyin parol."""

    username = State()
    password = State()
