# NNP Telegram boti (`parranda_bot`)

«Navobod naslli parranda qisqarmasi» (NNP) platformasining Telegram boti.
aiogram 2.25.2, Python 3.11. Backend bilan aloqa qoidalari: `../docs/API_CONTRACT.md` (3-bo‘lim, «Bot-only endpoints») va
`../docs/API_CONTRACT_V2.md` (5-bo‘lim, `/reports`).

## Imkoniyatlar

- `/start` — akkaunt bog‘langan bo‘lsa salomlashuv va menyu; bog‘lanmagan bo‘lsa login → parol orqali kirish
  (parolli xabar darhol o‘chiriladi).
- `/menu`, `/profile`, `/reports`, `/help`, `/cancel`, `/logout` (tasdiqlash tugmalari bilan).
- Rolga qarab menyu: xonadon egasi — «📍 Lokatsiyani yuborish», «📊 Hisobot», «👤 Profil», «ℹ️ Yordam»;
  administrator va omborchi — «📊 Hisobot», «👤 Profil», «ℹ️ Yordam».
- `/reports` va «📊 Hisobot» — bugungi statistika (pastga qarang).
- «🚀 PLATFORMANI OCHISH» Web App tugmasi va chat menyusidagi «Platforma» tugmasi (faqat `WEBAPP_URL` https bo‘lsa).
- Bildirishnomalar: har 3 soniyada backend navbatidan (`bot/notifications/pending`) xabarlarni olib yuboradi,
  natijani `bot/notifications/{id}/result` ga qaytaradi. Telegram cheklovi (`RetryAfter`) bo‘lsa kutadi,
  backend ishlamasa sikl to‘xtamaydi — kutib, qayta urinadi.

## `/reports` — hisobot va statistika

Manba: `GET bot/users/{telegram_id}/summary` (`X-Bot-Token` bilan, har safar yangidan — kesh yo‘q).
Barcha ko‘rsatkichlar backendda `API_CONTRACT_V2.md` 1-bo‘lim formulalari bo‘yicha hisoblanadi; bot faqat formatlaydi.
Matn shablonlari kontraktning 5.2-bo‘limidagi bilan aynan bir xil (testlar so‘zma-so‘z tekshiradi).

| Rol (backend qaytargan `role`) | Matn | Web App tugmasi |
|---|---|---|
| `OWNER` | «NNP — XONADON HISOBOTI»: xonadon, parranda soni, bugungi hisobot (✅/❌), bugun tuxum/yem/nobud, oxirgi 7 kun (tuxum, tuxumdorlik, yem, nobud, hisobotlar `6 / 7`) | `WEBAPP_URL/my` |
| `ADMIN`, `WAREHOUSE` | «NNP — BUGUNGI HOLAT»: hisobot topshirgan xonadonlar `8 / 11 (72.7%)`, tuxum, tuxumdorlik, yem sarfi, nobud, jami parranda (xonadonlarda · markazda), kam qolgan mahsulotlar | `WEBAPP_URL/stats` |

Formatlash (`utils/formatting.py`, backenddagi `common/formatting.py` bilan bir xil qoida):
sonlar minglik bo‘shliq bilan, kasrning oxirgi nollari tashlanadi (`2 800`, `310.5`, `380`);
foizlar doim 1 xona kasr, `ROUND_HALF_UP` (`81.2%`, `100.0%`); `null` → `—` (birliksiz);
sanalar `DD.MM.YYYY` (backend `date` maydoni, u bo‘lmasa Toshkent vaqti, UTC+5).
Hisobot topshirilmagan kun «Bugun tuxum» va «Bugun yem» — `—`. Xonadon nomi va kodi HTML uchun ekranlanadi.
«🔎 Web App orqali ko‘rish» tugmasi faqat `WEBAPP_URL` https bo‘lsa qo‘shiladi; aks holda xabar rolga mos menyu bilan keladi.

Xatolar: foydalanuvchi bog‘lanmagan (`404`) → «Siz hali tizimga kirmagansiz… /start»;
bloklangan yoki xonadon biriktirilmagan (`403`) → backend matni `⚠️ …`;
backend ishlamasa → «Server bilan aloqa yo‘q, birozdan keyin urinib ko‘ring.»; `5xx` yoki kutilmagan javob → «Serverda xatolik yuz berdi…».
Login jarayonida (parol bosqichida) `/reports` parol sifatida yuborilmaydi.

### Shartnomaga oid izohlar

Kontraktda aniq yozilmagan joylarda tanlangan eng sodda xatti-harakat (`API_CONTRACT_V2.md`, 5.2):

- `403` matni oldiga `⚠️ ` qo‘shiladi va HTML uchun ekranlanadi; boshqa o‘zgartirish yo‘q.
- `role` `OWNER` bo‘lmasa (`ADMIN`, `WAREHOUSE`) — «BUGUNGI HOLAT» matni.
- `report_discipline_pct` `null` bo‘lsa (faol xonadon yo‘q) qavs ichida `(—)` yoziladi: `0 / 0 (—)`.
- «Hisobotlar: X / Y» — backenddagi `last_7d.reports` / `last_7d.expected` qiymatlari o‘zgarishsiz.
  Kontraktga ko‘ra `reports` barcha hisobotlarni, `expected` esa faqat kutilgan kunlarni (xonadon yaratilgan
  kundan keyin, parranda bor kunlar) sanaydi, shuning uchun xonadon yaratilishidan oldingi sanaga kiritilgan
  hisobotlar bo‘lsa `X > Y` bo‘lishi mumkin (masalan, demo ma’lumotlarda `7 / 1`). Bot buni o‘zi qayta hisoblamaydi.
- Web App tugmasi bo‘lsa xabar inline tugma bilan yuboriladi (avvalgi reply menyu joyida qoladi);
  tugma bo‘lmasa xabar rolga mos reply menyu bilan keladi.

## Muhit o‘zgaruvchilari (`.env`)

`.env.dist` dan nusxa olib `.env` yarating:

| Kalit | Majburiy | Tavsif |
|---|---|---|
| `BOT_TOKEN` | ha | @BotFather bergan token. Hech qayerga (git, chat) joylamang. |
| `ADMINS` | yo‘q | Bot ishga tushganda xabar oladigan Telegram ID lar, vergul bilan. |
| `ip` | yo‘q | Xosting IP (standart `localhost`). |
| `API_URL` | yo‘q | Django API manzili, standart `http://127.0.0.1:8000/api` (oxirida `/` yo‘q). |
| `BOT_API_TOKEN` | ha | Backend bilan umumiy maxfiy kalit (pastga qarang). |
| `WEBAPP_URL` | yo‘q | Next.js Web App ning ochiq **https** manzili, masalan ngrok. |

### `BOT_API_TOKEN`

Bot backendga har bir so‘rovda `X-Bot-Token: <BOT_API_TOKEN>` sarlavhasini yuboradi.
Qiymat `parranda_backend/.env` dagi `BOT_API_TOKEN` bilan **aynan bir xil** bo‘lishi kerak.
Mos kelmasa, backend `403` qaytaradi: foydalanuvchi «Serverda xatolik yuz berdi» xabarini ko‘radi,
bot logida esa `BOT_API_TOKEN` ni tekshirish haqida xato yoziladi.

Tasodifiy kalit yaratish:

```powershell
venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Nima uchun `WEBAPP_URL` https bo‘lishi shart

Telegram Web App tugmalari (`web_app`) va chat menyusi tugmasi faqat `https://` manzillarni ochadi.
Lokal ishlab chiqishda Next.js (`localhost:3000`) ni ngrok orqali tashqariga chiqaring:

```powershell
ngrok http 3000
```

va berilgan `https://....ngrok-free.app` manzilini `WEBAPP_URL` ga yozing (oxirida `/` siz).
Next.js `/api/...` so‘rovlarini o‘zi Django ga proksi qiladi, shuning uchun bitta tunnel yetarli.
`WEBAPP_URL` bo‘sh yoki `http://` bo‘lsa, bot Web App tugmalarini ko‘rsatmaydi va
«Platforma havolasi hali sozlanmagan» deb yozadi; bildirishnomalar tugmasiz yuboriladi.

## Ishga tushirish (Windows)

```powershell
cd E:\Haydar_bobo\parranda_bot
python -m venv venv                      # bir marta
venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.dist .env                      # so‘ng .env ni to‘ldiring
venv\Scripts\python.exe app.py
```

Avval backend (`parranda_backend`, `127.0.0.1:8000`) ishlayotgan bo‘lishi kerak.
Bot backendga ulana olmasa, foydalanuvchiga «Server bilan aloqa yo‘q, birozdan keyin urinib ko‘ring.» deb javob beradi.

## Testlar

```powershell
venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

- `tests/test_bot.py` — API klienti (lokal aiohttp test serveri kontrakt shakllarida, `summary` ham) va bildirishnoma yuboruvchi.
- `tests/test_handlers.py` — handlerlar dispatcher orqali: Telegram so‘rovlari ushlab olinadi, haqiqiy token kerak emas.
  `ReportsTests` — `/reports` matnlari kontrakt shablonlariga so‘zma-so‘z mosligi, `—`, ekranlash, Web App yo‘llari, 403/404/503/500.
- `tests/test_logistics_tasks.py` — `/tasks` ro‘yxatlari (L/O/W/A), callback ma'lumoti tekshiruvi, tugmalar
  (qabul, yo‘lga chiqish, egasining tasdig‘i), dalil rasmi bosqichi (rasm, PDF, albom, xatolar, `/cancel`),
  muammo matni bosqichi va API klientining multipart yuklashi — holat mashinali soxta backend bilan.
- `tests/test_formatting.py` — sonlar, foizlar (half-up), sanalar, `—`.
- `tests/test_config.py` — majburiy sozlamalar (`BOT_TOKEN`, `BOT_API_TOKEN`) bo‘sh bo‘lsa bot darhol to‘xtashi va `WEBAPP_URL` https tekshiruvi.
  `.env` mavjud bo‘lsa bu 3 ta test o‘tkazib yuboriladi (skip); ularni ham ishga tushirish uchun loyihani `.env`siz vaqtinchalik papkaga nusxalab, testlarni o‘sha yerda ishga tushiring.

Testlar Telegramga hech narsa yubormaydi va polling ishga tushirmaydi.

## Tuzilma

```
app.py                  ishga tushirish, on_startup / on_shutdown
loader.py               bot, dispatcher, API klienti
data/config.py          .env sozlamalari
handlers/users/         start, login (FSM), menu/profil, reports, tasks, task_actions (FSM), notifications,
                        help, cancel, logout, location, fallback
handlers/errors/        backend va Telegram xatolarini qayta ishlash
keyboards/default/      rolga mos reply menyu
keyboards/inline/       Web App va logout tugmalari
middlewares/            throttling
states/                 LoginStates, DeliveryProof, DeliveryIssue
utils/api.py            backend klienti (aiohttp, X-Bot-Token, 10 s timeout)
utils/logistics_tasks.py  topshiriq matnlari, inline tugmalar, callback ma'lumoti
utils/vet_tasks.py      VET / ADMIN /tasks xulosalari
utils/formatting.py     sonlar, foizlar, sanalar formatlash (`2 800`, `81.2%`, `04.11.2026`, `—`)
utils/notifier.py       bildirishnomalar navbatini yuboruvchi fon jarayoni
utils/set_bot_commands.py  buyruqlar ro‘yxati va chat menyusi tugmasi
```

## 3-bosqich (V3) poydevori

- Rollar: `LOGISTICS` (Logistika xodimi), `VET` (Veterinar). Menyu (§14.4): OWNER — lokatsiya · `📋 Topshiriqlar`
  `🔔 Bildirishnomalar` · hisobot/profil/yordam; LOGISTICS — `📋 Topshiriqlarim`; VET — `📋 Bugungi ishlar`; ADMIN/WAREHOUSE — `📋 Topshiriqlar`.
- `/tasks` (`handlers/users/tasks.py`) — `GET bot/users/{tid}/tasks` asosida (§14.2):
  - **LOGISTICS** — sarlavha (faol / yo‘lda / biriktirilmagan / muddati o‘tgan) va har bir topshiriq alohida xabar
    (eng ko‘pi 10 ta): `🚚 LG-000012 — Biriktirildi`, xonadon, manzil, yuk, transport, haydovchi, reja sanasi;
  - **OWNER** — sarlavha (tasdiq kutilmoqda / yo‘lda, ochiq buyurtmalar, yaqin veterinariya ishlari) va
    yetkazib berishlar alohida xabar;
  - **VET** / **ADMIN** / **WAREHOUSE** — bitta xulosa xabari va Web App tugmalari (`/vet`, `/vet/requests`;
    `/orders`, yangi buyurtmalar `/orders/{id}`, `/logistics`; `/warehouse`, `/logistics`).
  - Backend javob bermasa — rolga mos Web App bo‘limi tugmasi.
- Topshiriq tugmalari (`handlers/users/task_actions.py`, matn va klaviaturalar — `utils/logistics_tasks.py`).
  Tugmalar faqat server qaytargan `allowed_actions` bo‘yicha chiziladi, har bir amalni server qayta tekshiradi:

  | Tugma | callback | Backend |
  |---|---|---|
  | `✅ Qabul qilish` | `t:acc:<id>` | `POST bot/tasks/{id}/accept` |
  | `🛻 Yo‘lga chiqdim` | `t:go:<id>` | `POST bot/tasks/{id}/start` (ombordan chiqim shu paytda) |
  | `📦 Yetkazdim (foto bilan)` | `t:dlv:<id>` | FSM `DeliveryProof.photo` → `POST bot/files` (`DELIVERY_PROOF`) → `POST bot/tasks/{id}/deliver` |
  | `✅ Qabul qildim` (egasi) | `t:cnf:<id>` | `POST bot/tasks/{id}/confirm` (`received_ok=true`) |
  | `⚠️ Muammo bor` (egasi) | `t:iss:<id>` | FSM `DeliveryIssue.note` (3–1000 belgi) → `confirm` (`received_ok=false`) |

  Callback ma'lumoti qat'iy shablon bilan tekshiriladi (`t:(acc|go|dlv|cnf|iss):<1…2⁶³−1>`, ≤ 64 bayt);
  boshqasi yoki guruh chatidan kelgani — «tugma eskirgan» va backendga so‘rov yuborilmaydi.
  Muvaffaqiyatda xabar tahrirlanadi (yangi holat, yangi tugmalar), callback javobi `Bajarildi ✅`.
  `400/403/404/409` — server matni alert sifatida ko‘rsatiladi va xabar `/tasks` ma'lumoti bo‘yicha yangilanadi
  (topshiriq ro‘yxatda bo‘lmasa amal tugmalari olib tashlanadi, Web App tugmasi qoladi).
  Aloqa yo‘q / `429` / `5xx` — umumiy xatolik handleri alert bilan javob beradi.
- Dalil bosqichi: rasm (eng katta o‘lcham ≤ 10 MB) yoki hujjat (JPG, PNG, WEBP, PDF) qabul qilinadi; boshqa xabar —
  ko‘rsatma qayta yuboriladi. Bosqich yuklash vaqtida band qilinadi (`DeliveryProof.uploading`): albomdagi qolgan
  rasmlar jim o‘tkazib yuboriladi, takroriy yuborish ikkinchi marta yuklanmaydi. Fayl rad etilsa (`400`), aloqa
  bo‘lmasa yoki Telegramdan fayl olinmasa — bosqich ochiq qoladi (qayta yuborish yoki `/cancel`);
  `403/404/409` — bosqich yopiladi. Fayl hajmi va turi backendda ham tekshiriladi (V3 §4.2).
- `/notifications` (`handlers/users/notifications.py`) — `GET bot/users/{tid}/notifications?limit=10`, o‘qilmaganlar `🆕`.
- `/reports` LOGISTICS va VET matnlari (§14.4).

## Fix bosqichi

- **Vaqtinchalik parol** (TZ §3): `must_change_password` bo‘lsa `/profile`, `/menu`, `/logout` dan boshqa buyruqlar va
  topshiriq tugmalari ishlamaydi — “⚠️ Sizda vaqtinchalik parol…” va platforma tugmasi (`require_user(...,
  allow_temp_password=)`, `send_password_prompt`). Backend ham bu amallarga `403` qaytaradi.
- **`/settings`** — shaxsiy bildirishnoma sozlamalari Web App’da (qo‘ng‘iroqcha → ⚙️); buyruqlar ro‘yxati va `/help` da.
- **Go‘sht**: `/reports` matnlarida go‘sht qatori faqat qiymat > 0 bo‘lsa (`meat_kg`).
- **Telegram 5xx** (`RestartingTelegram` yoki aynan `TelegramAPIError` statusiz) tarmoq uzilishi kabi: urinish
  hisoblanmaydi, xabar `PENDING` qoladi, sikl kutishi 3 → 60 s gacha oshadi (`utils/notifier.py::is_telegram_server_error`).
- Testlar: 139 ta (`venv\Scripts\python.exe -m unittest discover -s tests -t .`).

## Docker (server)

Bu papkada o‘z `Dockerfile` va `docker-compose.yml` bor. U `parranda_backend` yaratadigan `nnp_net` tarmog‘iga ulanadi, shuning uchun backend birinchi ishga tushiriladi.
To‘liq yo‘riqnoma: `parranda_backend/DEPLOY.md`.

```bash
docker compose build
docker compose up -d
```
