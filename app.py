import logging

from aiogram import Dispatcher, executor

from data import config
from loader import api, bot, dp
import middlewares, filters, handlers  # noqa: F401,E401 — handlerlarni ro'yxatdan o'tkazish
from utils.notifier import NotificationWorker
from utils.notify_admins import on_startup_notify
from utils.set_bot_commands import set_default_commands, set_menu_button

log = logging.getLogger(__name__)

notifier = NotificationWorker(bot=bot, api=api, webapp_url=config.WEBAPP_URL)


async def on_startup(dispatcher: Dispatcher) -> None:
    if config.WEBAPP_URL and not config.WEBAPP_ENABLED:
        log.warning("WEBAPP_URL https bilan boshlanmaydi — Web App tugmalari o‘chirildi: %s", config.WEBAPP_URL)
    await set_default_commands(dispatcher.bot)
    await set_menu_button(dispatcher.bot, config.WEBAPP_URL)
    await on_startup_notify(dispatcher.bot, config.ADMINS)
    notifier.start()


async def on_shutdown(dispatcher: Dispatcher) -> None:
    # Telegram sessiyasi va FSM xotirasini executor o'zi yopadi (Executor._shutdown).
    await notifier.stop()
    await api.close()


if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown, skip_updates=True)
