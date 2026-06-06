"""
Sozlamalar NAMUNASI.

1) Nusxa oling:   config.example.py  ->  config.py
2) Quyidagilarni to'ldiring:
   - BOT_TOKEN  : @BotFather da YANGI bot oching (Dilux/factory botlardan alohida)
   - BASE_URL   : server qaysi HTTPS manzilda turishi (Mini App + webhook shu yerda)
   - Har xodimning Telegram ID si: @userinfobot ga /start yozsa, ID beradi

ESLATMA: config.py ni hech kimga bermang / git ga qo'shmang (token bor).
"""

# ── Telegram bot ──
BOT_TOKEN = "0000000000:XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"

# Server ochiq HTTPS manzili (oxirida / belgisisiz). Mini App va webhook shu yerda.
# Masalan: "https://otk.sizning-domeningiz.uz"  yoki Render/Railway bergan URL.
BASE_URL = "https://example.com"

# Lokal test (Telegramsiz brauzerда sinash) uchun True qiling.
# True bo'lganда ?dev=<telegram_id> orqali kim ekanini bildiriб bo'ladi.
# PRODUCTION'да HAR DOIM False bo'lsin!
DEV = False

# Kunlik hisobot vaqti (server soati bo'yicha — server TZ=Asia/Tashkent bo'lsin).
# Shu vaqtда Operator + Rahbarга: o'sha kungi barcha PDF lar + umumiy Кв² (Алюминь/ПВХ alohida).
REPORT_TIME = "18:30"

# ════════════════════════════════════════════════════════════
#  ROLLAR — Telegram ID + ism (ism PDF dagi imzo tagida chiqadi)
# ════════════════════════════════════════════════════════════

# OTK — to'ldiradi + imzolaydi (boshlovchi). Tur bo'yicha 2 kishi.
OTK = {
    "alyumin": {"id": 111111111, "name": "Нажмитдинов А."},
    "pvh":     {"id": 222222222, "name": "Нажмитдинов А."},
}

# MASTER — tasdiqlaydi + imzolaydi. Tur bo'yicha 2 kishi.
MASTER = {
    "alyumin": {"id": 333333333, "name": "Мамаджанов А."},
    "pvh":     {"id": 444444444, "name": "Мамаджанов А."},
}

# ГП (Зав.склад ГП) — oxirgi tasdiq + imzo -> накладной yopiladi. 1 kishi.
GP = {"id": 555555555, "name": "Нематуллаев Э."}

# Yopilgan накладнойнинг PDF si shu kishilarга boradi (uchchаласи chop eta oladi)
OPERATORS = [666666666, 777777777]   # 1-operator (ma'lumot/arxiv), 2-operator (chop etish)
RAHBAR = 888888888                   # ishlab chiqarish rahbari (kuzatadi + chop etadi)


# ── Yordamchi: Telegram ID -> rol ──
def role_of(uid: int):
    """Foydalanuvchi ID si bo'yicha rolni qaytaradi yoki None."""
    uid = int(uid)
    for tur, v in OTK.items():
        if v["id"] == uid:
            return {"role": "otk", "tur": tur, "name": v["name"]}
    for tur, v in MASTER.items():
        if v["id"] == uid:
            return {"role": "master", "tur": tur, "name": v["name"]}
    if uid == GP["id"]:
        return {"role": "gp", "name": GP["name"]}
    if uid in OPERATORS:
        return {"role": "operator", "name": ""}
    if uid == RAHBAR:
        return {"role": "rahbar", "name": ""}
    return None

# Tayyor PDF oluvchilar ro'yxati (takrorlanmas)
def pdf_recipients():
    return list(dict.fromkeys([*OPERATORS, RAHBAR]))
