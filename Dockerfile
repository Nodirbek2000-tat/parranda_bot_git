# NNP bot — aiogram 2.25.2
#
# Bot port ochmaydi va bazaga tegmaydi: Telegram'ga o'zi ulanadi (long polling)
# va backend bilan ichki tarmoq orqali gaplashadi.
# aiogram 2.25.2 -> aiohttp 3.8.6 Python 3.11 ni talab qiladi (3.12+ da o'rnatilmaydi).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 nnp && chown -R nnp:nnp /app
USER nnp

CMD ["python", "app.py"]
