import logging

from aiogram import Bot, types
from aiogram.utils.exceptions import TelegramAPIError

log = logging.getLogger(__name__)

COMMANDS: list[types.BotCommand] = [
    types.BotCommand("start", "Botni ishga tushirish / tizimga kirish"),
    types.BotCommand("menu", "Asosiy menyu"),
    types.BotCommand("profile", "Mening profilim"),
    types.BotCommand("tasks", "Mening topshiriqlarim"),
    types.BotCommand("notifications", "Bildirishnomalar"),
    types.BotCommand("reports", "Hisobot va statistika"),
    types.BotCommand("settings", "Bildirishnoma sozlamalari"),
    types.BotCommand("help", "Yordam"),
    types.BotCommand("cancel", "Joriy amalni bekor qilish"),
    types.BotCommand("logout", "Tizimdan chiqish"),
]

MENU_BUTTON_TEXT = "Platforma"


async def set_default_commands(bot: Bot) -> None:
    await bot.set_my_commands(COMMANDS)


async def set_menu_button(bot: Bot, webapp_url: str) -> None:
    """Chat menyusi tugmasi: https manzil bo'lsa Web App, aks holda buyruqlar ro'yxati."""
    if webapp_url.startswith("https://"):
        button: types.MenuButton = types.MenuButtonWebApp(
            text=MENU_BUTTON_TEXT, web_app=types.WebAppInfo(url=webapp_url)
        )
    else:
        button = types.MenuButtonCommands()
    try:
        await bot.set_chat_menu_button(menu_button=button)
    except TelegramAPIError as exc:
        log.warning("Menyu tugmasini o‘rnatib bo‘lmadi: %s", exc)
