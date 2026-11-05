"""Bot sozlamalari: barcha qiymatlar .env faylidan (yoki muhit o'zgaruvchilaridan) o'qiladi."""
from environs import Env

env = Env()
env.read_env()


def _required(name: str) -> str:
    """Majburiy qiymat: bo'sh bo'lsa bot tushunarli xabar bilan darhol to'xtaydi."""
    value = env.str(name, default="").strip()
    if not value:
        raise RuntimeError(f"{name} ko‘rsatilmagan: .env faylini .env.dist asosida to‘ldiring.")
    return value


# Telegram bot tokeni (@BotFather). Majburiy.
BOT_TOKEN: str = _required("BOT_TOKEN")

# Bot ishga tushganda xabar oladigan Telegram ID lar (vergul bilan). Ixtiyoriy.
ADMINS: list[int] = env.list("ADMINS", default=[], subcast=int)

# Xosting IP manzili (shablondan qolgan, ixtiyoriy).
IP: str = env.str("ip", default="localhost")

# Django API manzili (oxirida "/" bo'lmasin).
API_URL: str = env.str("API_URL", default="http://127.0.0.1:8000/api").strip().rstrip("/")

# Backend bilan umumiy maxfiy kalit (X-Bot-Token sarlavhasi). Majburiy.
BOT_API_TOKEN: str = _required("BOT_API_TOKEN")

# Next.js Web App ning ochiq https manzili (masalan ngrok). Bo'sh bo'lsa, Web App tugmalari ko'rsatilmaydi.
WEBAPP_URL: str = env.str("WEBAPP_URL", default="").strip().rstrip("/")

# Telegram Web App faqat https manzillarni qabul qiladi.
WEBAPP_ENABLED: bool = WEBAPP_URL.startswith("https://")
