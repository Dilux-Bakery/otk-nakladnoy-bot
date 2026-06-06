# OTK Накладной bot

Zavod (Алюминь / ПВХ) uchun **ichki накладной** tizimi — Telegram bot + Mini App + PDF.
Dilux/factory botlardan **alohida**, mustaqil loyiha.

## Jarayon (imzo zanjiri)

```
OTK (Alu|PVC)        Master (Alu|PVC)      Зав.склад ГП          ✅ YOPILDI
ma'lumot + imzo  →   tasdiq + imzo     →   tasdiq + imzo    →    PDF tayyor
                                                                    │
                                       PDF ──► Operator-1, Operator-2, Rahbar
                                               (uchchаласи chop etadi)
```

- **Тур** (Алюминь/ПВХ) накладнойни qaysi OTK va Master ko'rishini belgilaydi.
- Har 3 imzo — **canvas** (barmoq) bilan, PDF da chiqadi.
- Yopilgach PDF avtomatik 3 kishiga boradi.
- Har kim **Счёт raqami** orqali eski накладнойларни qidiradi.

## Fayllar

| Fayl | Vazifa |
|---|---|
| `webapp/` | Mini App — yaratish (OTK) + imzolash (Master/ГП) |
| `server.py` | FastAPI: webapp + /api + Telegram /webhook (bitta xizmat) |
| `db.py` | SQLite — накладной + imzolar + status |
| `pdf.py` | накладной PDF (fpdf2) |
| `config.py` | token + rollar/ID/ismlar (o'zingiz yaratasiz) |
| `fonts/` | Kirill shrift (DejaVuSans.ttf) |

## O'rnatish

```bash
pip install -r requirements.txt
copy config.example.py config.py     # keyin to'ldiring (token, ID lar)
```

**Shrift:** `fonts/DejaVuSans.ttf` bo'lishi kerak (kirill uchun). Bo'lmasa kod
Windows `arial.ttf` yoki Linux tizim DejaVu siga o'tadi, lekin serverда bundle qilish ishonchliroq.

## Ishga tushirish

```bash
uvicorn server:app --host 0.0.0.0 --port 8080
```

Telegram Mini App va webhook **HTTPS** talab qiladi. Variantlar:
- Domen + TLS bilan VPS (nginx → 8080)
- Render / Railway (bepul HTTPS URL beradi)

`BASE_URL` to'g'ri bo'lsa, server ishga tushganда webhook avtomatik o'rnatiladi.

## Kerak bo'ladi
- @BotFather dan **yangi bot token**
- **8 ta Telegram ID**: 2 OTK, 2 Master, 1 ГП, 2 Operator, 1 rahbar (@userinfobot dan)
- **HTTPS host**
