from aiogram.dispatcher.filters.state import State, StatesGroup


class DeliveryProof(StatesGroup):
    """«📦 Yetkazdim»: dalil rasmi kutilmoqda (``photo``) → yuklanmoqda (``uploading``, takroriy yuborishga qarshi)."""

    photo = State()
    uploading = State()


class DeliveryIssue(StatesGroup):
    """Xonadon egasi «⚠️ Muammo bor»: qisqa izoh kutilmoqda (``note``) → yuborilmoqda (``sending``)."""

    note = State()
    sending = State()
