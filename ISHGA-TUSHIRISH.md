# OTK Накладной — LOCAL ishga tushirish (kompyuterда)

Ma'lumot kompyuteringizдаги `nakladnoy.db` faylда saqlanadi — **o'chmaydi**.
Har kuni 18:30 da `backups/` papkaga avtomatik **zaxira** olinadi.

---

## 1. Bir martalik: kutubxonalar
`install.bat` ni ikki marta bosing (Python kutubxonalarini o'rnatadi).

## 2. `.env` faylni to'ldirish
`.env.example` ни **`.env`** deb nusxalang, ichini to'ldiring:
- `BOT_TOKEN` — @BotFather dan
- 8 ta `..._ID` — har xodimning Telegram ID si
- `BASE_URL` — (4-qadamда olinadi)

> **ID larni qanday bilish:** 3-qadamда botни yoqib, har xodim botга `/start` yozsin —
> bot uning ID sini aytadi. O'sha ID larni `.env` ga yozasiz.

## 3. Botni yoqish
`start.bat` ни bosing. Server `http://localhost:8080` da ishlaydi.
(Bu oyna ochiq turishi kerak — yopilsa bot to'xtaydi.)

## 4. Telefonда ishlashi uchun — HTTPS (Cloudflare Tunnel, bepul)
Telegram Mini App ochiq HTTPS manzil talab qiladi. Lokal kompyuterни shunday ochamiz:

1. `cloudflared.exe` ни yuklab oling:
   github.com/cloudflare/cloudflared/releases → `cloudflared-windows-amd64.exe`
2. Yangi oynada ishga tushiring:
   ```
   cloudflared tunnel --url http://localhost:8080
   ```
3. U `https://xxxxx.trycloudflare.com` ko'rinishидаги manzil beradi.
4. Shu manzilni `.env` dagi `BASE_URL` ga yozing → `start.bat` ни qaytadan yoqing.

Tamom — endi botда «Накладной yaratish» tugmasi telefonда ochiladi.

---

## Eslatmalar
- **Kompyuter + internet doim yoniб turishi kerak** (bot 24/7 ishlashi uchun).
- Cloudflare bepul manzili **har safar o'zgaradi** — qayta yoqsangiz, yangi
  `BASE_URL` ни `.env` ga yozish kerak. (Doimiy, barqaror manzil uchun keyinroq
  arzon VPS yoki domen — bir marta sozlaб qo'yiladi.)
- **Zaxira:** `backups/` papka + istasangiz uни Google Drive/USB ga ham nusxalang.

## Faqat sinash (Telegramsiz)
Bot/tunnel sozlamасдан UI ни ko'rish uchun — `OTK-DEMO.html` ни oching (offlayn demo).
