"""
OTK Накладной — backend (FastAPI) + Telegram webhook (bitta xizmat).

Ishga tushirish:
    uvicorn server:app --host 0.0.0.0 --port 8080

Beradi:
    /webapp/...   -> Mini App (statik)
    /api/...      -> REST (me, create, get, sign, search)
    /webhook      -> Telegram update'lari
"""
import hashlib
import hmac
import json
import os
import sys
import urllib.parse

# Windows konsoli (cp1251) kirill/emoji print'ларида yiqilmasin
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import config
import db
import pdf

app = FastAPI()
API = f"https://api.telegram.org/bot{config.BOT_TOKEN}"
WEBHOOK_SECRET = hashlib.sha256(("wh:" + config.BOT_TOKEN).encode()).hexdigest()[:40]

ROLE_UZ = {"otk": "OTK", "master": "Master", "gp": "Зав.склад ГП",
           "operator": "Operator", "rahbar": "Ishlab chiqarish rahbari"}
SCHET_PREFIXES = ("710", "711", "243", "249")


# ════════════════ Telegram Bot API ════════════════
async def tg(method, **params):
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{API}/{method}", json=params)
            return r.json()
    except Exception as e:
        print("tg() xato:", method, e)
        return {"ok": False, "error": str(e)}


async def send_message(chat_id, text, reply_markup=None):
    p = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        p["reply_markup"] = reply_markup
    return await tg("sendMessage", **p)


async def send_pdf(chat_id, pdf_bytes, filename, caption=""):
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"{API}/sendDocument",
                data={"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML"},
                files={"document": (filename, pdf_bytes, "application/pdf")},
            )
            return r.json()
    except Exception as e:
        print("send_pdf() xato:", chat_id, e)
        return {"ok": False, "error": str(e)}


def webapp_btn(text, mode, nid=None):
    url = f"{config.BASE_URL}/webapp/?mode={mode}"
    if nid:
        url += f"&id={nid}"
    return {"inline_keyboard": [[{"text": text, "web_app": {"url": url}}]]}


# ════════════════ initData / auth ════════════════
def validate_init_data(init_data: str) -> dict:
    parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    h = parsed.pop("hash", None)
    if not h:
        raise ValueError("no hash")
    dcs = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed))
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, h):
        raise ValueError("bad hash")
    return json.loads(parsed.get("user", "{}"))


def uid_from(body: dict) -> int:
    init = body.get("initData") or ""
    if init:
        return int(validate_init_data(init)["id"])
    if getattr(config, "DEV", False) and body.get("dev"):
        return int(body["dev"])
    raise PermissionError("no-auth")


def err(msg, code=400):
    return JSONResponse(status_code=code, content={"error": msg})


# ════════════════ API ════════════════
@app.post("/api/me")
async def api_me(request: Request):
    body = await request.json()
    try:
        uid = uid_from(body)
    except Exception:
        return err("Ruxsat yo‘q", 403)
    role = config.role_of(uid)
    if not role:
        return err("Siz ro‘yxatda yo‘qsiz. ID: " + str(uid), 403)
    return role


@app.post("/api/create")
async def api_create(request: Request):
    body = await request.json()
    try:
        uid = uid_from(body)
    except Exception:
        return err("Ruxsat yo‘q", 403)
    role = config.role_of(uid)
    if not role or role["role"] != "otk":
        return err("Faqat OTK yarata oladi", 403)
    n = body.get("nakladnoy", {})
    schet = (n.get("schet") or "").strip()
    if not schet.startswith(SCHET_PREFIXES) or len(schet) < 6:
        return err("Счёт noto‘g‘ri (710/711/243/249 bilan, ≥6 raqam)")
    items = n.get("items") or []
    if not items:
        return err("Kamida bitta o‘lcham kiriting")
    nid = db.create({
        "nomer": n.get("nomer", ""), "tur": role["tur"], "schet": schet,
        "mtur": n.get("mtur", ""), "mahsulot": n.get("mahsulot", ""),
        "rang": n.get("rang", ""), "profil": n.get("profil", ""), "items": items,
        "otk_id": uid, "otk_name": role["name"], "otk_imzo": body.get("imzo", ""),
    })
    # Mos turdagi Master'ga xabar
    master = config.MASTER.get(role["tur"])
    if master:
        await send_message(
            master["id"],
            f"🆕 Yangi накладной <b>№{n.get('nomer','')}</b> ({pdf.TUR_LABEL.get(role['tur'])})\n"
            f"Счёт: {schet} · {n.get('mtur','')} · {n.get('rang','')}\nTasdiqlashingiz kutilmoqda 👇",
            webapp_btn("✍️ Ko‘rib imzolash", "sign", nid),
        )
    return {"ok": True, "id": nid}


@app.post("/api/get")
async def api_get(request: Request):
    body = await request.json()
    try:
        uid = uid_from(body)
    except Exception:
        return err("Ruxsat yo‘q", 403)
    if not config.role_of(uid):
        return err("Ruxsat yo‘q", 403)
    n = db.get(int(body["id"]))
    if not n:
        return err("Topilmadi", 404)
    return {"nakladnoy": n}


@app.post("/api/sign")
async def api_sign(request: Request):
    body = await request.json()
    try:
        uid = uid_from(body)
    except Exception:
        return err("Ruxsat yo‘q", 403)
    role = config.role_of(uid)
    if not role or role["role"] not in ("master", "gp"):
        return err("Imzolash huquqi yo‘q", 403)
    nid = int(body["id"])
    n = db.get(nid)
    if not n:
        return err("Topilmadi", 404)
    if role["role"] == "master" and role.get("tur") != n["tur"]:
        return err("Bu sizning turingiz emas", 403)
    ok, res, n2 = db.sign(nid, role["role"], uid, role["name"], body.get("imzo", ""))
    if not ok:
        return err("Navbat xato (status: " + str(res) + ")", 409)
    if res == "gp":                       # Master imzoladi -> ГП ga
        await send_message(
            config.GP["id"],
            f"📨 Накладной <b>№{n2['nomer']}</b> ({pdf.TUR_LABEL.get(n2['tur'])}) "
            f"Master tomonidan tasdiqlandi.\nYakuniy tasdig‘ingiz kutilmoqda 👇",
            webapp_btn("✍️ Ko‘rib imzolash", "sign", nid),
        )
    elif res == "closed":                 # ГП imzoladi -> yopildi, PDF tarqatamiz
        await distribute_pdf(n2)
    return {"ok": True, "status": res}


@app.post("/api/search")
async def api_search(request: Request):
    body = await request.json()
    try:
        uid = uid_from(body)
    except Exception:
        return err("Ruxsat yo‘q", 403)
    if not config.role_of(uid):
        return err("Ruxsat yo‘q", 403)
    rows = db.search_by_schet(body.get("schet", ""))
    # imzo blob'larini olib tashlaymiz (yengil javob)
    out = [{k: v for k, v in r.items() if not k.endswith("_imzo")} for r in rows]
    return {"results": out}


# ════════════════ PDF tarqatish ════════════════
async def distribute_pdf(n: dict):
    data = pdf.generate(n)
    fname = f"nakladnoy_{n.get('nomer','')}.pdf"
    cap = (f"✅ Накладной <b>№{n.get('nomer','')}</b> ({pdf.TUR_LABEL.get(n.get('tur'))}) yopildi\n"
           f"Счёт: {n.get('schet','')} · {n.get('mtur','')} · {n.get('rang','')}")
    for chat_id in config.pdf_recipients():
        await send_pdf(chat_id, data, fname, cap)


# ════════════════ Telegram webhook ════════════════
@app.post("/webhook")
async def webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    upd = await request.json()
    msg = upd.get("message")
    if msg:
        await on_message(msg)
    return {"ok": True}


async def on_message(msg):
    chat_id = msg["chat"]["id"]
    uid = msg["from"]["id"]
    text = (msg.get("text") or "").strip()
    role = config.role_of(uid)

    if text.startswith("/start"):
        return await on_start(uid, chat_id, role)
    if not role:
        return await send_message(chat_id, f"Siz ro‘yxatda yo‘qsiz.\nSizning ID: <code>{uid}</code>")
    # Счёт qidiruv (raqam yuborilsa)
    if text and text.replace(" ", "").isdigit() and len(text) >= 3:
        return await do_search(chat_id, text)
    await on_start(uid, chat_id, role)


async def on_start(uid, chat_id, role):
    if not role:
        return await send_message(chat_id, f"👋 Salom! Siz hali ro‘yxatda yo‘qsiz.\nSizning ID: <code>{uid}</code>\nBuni administratorga bering.")
    r = role["role"]
    if r == "otk":
        return await send_message(
            chat_id, f"👷 <b>OTK</b> ({pdf.TUR_LABEL.get(role['tur'])})\nYangi накладной yaratish uchun 👇",
            webapp_btn("➕ Накладной yaratish", "create"))
    if r in ("master", "gp"):
        pend = db.list_for_role(r, role.get("tur"))
        if not pend:
            return await send_message(chat_id, f"✅ <b>{ROLE_UZ[r]}</b> — hozircha navbatда накладной yo‘q.")
        await send_message(chat_id, f"📋 <b>{ROLE_UZ[r]}</b> — tasdig‘ingiz kutilayotган {len(pend)} ta:")
        for n in pend:
            await send_message(
                chat_id,
                f"№<b>{n['nomer']}</b> · {pdf.TUR_LABEL.get(n['tur'])} · Счёт {n['schet']} · {n['mtur']} · {n['rang']}",
                webapp_btn("✍️ Imzolash", "sign", n["id"]))
        return
    # operator / rahbar
    return await send_message(chat_id, f"🔎 <b>{ROLE_UZ[r]}</b>\nЭски накладнойни topish uchun <b>Счёт raqamini</b> yuboring.")


async def do_search(chat_id, schet):
    rows = db.search_by_schet(schet)
    if not rows:
        return await send_message(chat_id, f"🔎 Счёт «{schet}» bo‘yicha накладной topilmadi.")
    await send_message(chat_id, f"🔎 «{schet}» — {len(rows)} ta topildi:")
    st = {"master": "⏳ Master kutilmoqda", "gp": "⏳ ГП kutilmoqda", "closed": "✅ Yopilgan"}
    for n in rows[:15]:
        line = f"№<b>{n['nomer']}</b> · {pdf.TUR_LABEL.get(n['tur'])} · {n['mtur']} · {n['rang']} — {st.get(n['status'], n['status'])}"
        if n["status"] == "closed":
            await send_pdf(chat_id, pdf.generate(n), f"nakladnoy_{n['nomer']}.pdf", line)
        else:
            await send_message(chat_id, line)


# ════════════════ Statik + startup ════════════════
@app.on_event("startup")
async def _startup():
    db.init()
    if config.BASE_URL and "example.com" not in config.BASE_URL:
        res = await tg("setWebhook", url=f"{config.BASE_URL}/webhook",
                       secret_token=WEBHOOK_SECRET,
                       allowed_updates=["message", "callback_query"])
        print("setWebhook:", res)
    else:
        print("⚠️  BASE_URL sozlanmagan — webhook o‘rnatilmadi (lokal rejim).")


_HERE = os.path.dirname(os.path.abspath(__file__))
app.mount("/webapp", StaticFiles(directory=os.path.join(_HERE, "webapp"), html=True), name="webapp")


@app.get("/")
async def root():
    return JSONResponse({"ok": True, "service": "otk-nakladnoy"})
