"""Bot settings, read from .env (or the process environment)."""
from environs import Env

env = Env()
env.read_env()  # existing environment variables win over .env


def _required(name: str) -> str:
    value = env.str(name, default="").strip()
    if not value:
        raise RuntimeError(f"{name} ko‘rsatilmagan: .env faylini .env.dist asosida to‘ldiring.")
    return value


BOT_TOKEN: str = _required("BOT_TOKEN")
ADMINS: list[int] = env.list("ADMINS", default=[], subcast=int)
IP: str = env.str("ip", default="localhost")
API_URL: str = env.str("API_URL", default="http://127.0.0.1:8000/api").strip().rstrip("/")
BOT_API_TOKEN: str = _required("BOT_API_TOKEN")
# Public https address of the Web App. Telegram opens only https, so anything else disables the buttons.
WEBAPP_URL: str = env.str("WEBAPP_URL", default="").strip().rstrip("/")


def webapp_enabled() -> bool:
    return WEBAPP_URL.startswith("https://")
