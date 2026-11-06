"""NNP bot entry point: long polling + the notification loop.

Never run this locally with the production BOT_TOKEN: it would take the server bot's updates.
"""
import logging

from aiogram import Dispatcher, executor, types
from aiogram.utils.exceptions import TelegramAPIError

import config
import handlers  # noqa: F401  (registers the handlers)
from loader import api, bot, dp
from notifier import Notifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

COMMANDS = [
    types.BotCommand("start", "Tizimga kirish"),
    types.BotCommand("menu", "Asosiy menyu"),
    types.BotCommand("help", "Yordam"),
    types.BotCommand("cancel", "Amalni bekor qilish"),
]

notifier = Notifier(bot, api)


async def on_startup(dispatcher: Dispatcher) -> None:
    if not config.webapp_enabled():
        log.warning("WEBAPP_URL is not https: Web App buttons are disabled")
    try:
        await dispatcher.bot.set_my_commands(COMMANDS)
        if config.webapp_enabled():
            button = types.MenuButtonWebApp(text="Platforma", web_app=types.WebAppInfo(url=config.WEBAPP_URL))
        else:
            button = types.MenuButtonCommands()
        await dispatcher.bot.set_chat_menu_button(menu_button=button)
    except TelegramAPIError as exc:
        log.warning("Could not set commands / menu button: %s", exc)
    for admin_id in config.ADMINS:
        try:
            await dispatcher.bot.send_message(admin_id, "✅ NNP boti ishga tushdi.")
        except TelegramAPIError as exc:
            log.warning("Startup message to admin %s failed: %s", admin_id, exc)
    notifier.start()


async def on_shutdown(dispatcher: Dispatcher) -> None:
    await notifier.stop()
    await api.close()


if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown, skip_updates=True)
