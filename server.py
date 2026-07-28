"""
OTK Накладной — backend (FastAPI) + Telegram webhook (bitta xizmat).

Ishga tushirish:
    uvicorn server:app --host 0.0.0.0 --port 8080

Beradi:
    /webapp/...   -> Mini App (statik)
    /api/...      -> REST (me, create, get, sign, search)
    /webhook      -> Telegram update'lari
"""
import asyncio
import hashlib
import hmac
import io
import json
import os
import re
import shutil
import sys
import urllib.parse
import zipfile
from datetime import datetime, timedelta

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

# Webapp versiyasi (kesh-buster) — index.html o'zgarsa avtomat yangilanadi -> Telegram yangisini yuklaydi
_WEBAPP_INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp", "index.html")
try:
    WEBAPP_VER = str(int(os.path.getmtime(_WEBAPP_INDEX)))
except Exception:
    WEBAPP_VER = "1"


@app.middleware("http")
async def _webapp_no_cache(request: Request, call_next):
    """Webapp'ni Telegram keshlamasin — har safar yangisini yuklaydi."""
    resp = await call_next(request)
    if request.url.path.startswith("/webapp"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
    return resp

ROLE_UZ = {"otk": "OTK", "master": "Master", "gp": "Зав.склад ГП",
           "operator": "Operator", "rahbar": "Ishlab chiqarish rahbari",
           "admin": "Admin (barcha ma'lumot)"}
SCHET_PREFIXES = ("710", "711", "243", "249")


def _ref(n):
    """Накладнойни identifikatsiya — Счёт (WinCAD/Klaes) ko'rinadi (нomer emas)."""
    s = (n.get("schet") or "").strip()
    return "Счёт " + s if s else "№" + str(n.get("nomer", ""))


def _fname(n):
    """PDF fayl nomi — Счёт asosida."""
    base = n.get("schet_w") or n.get("schet_k") or n.get("nomer") or "x"
    return "nakladnoy_" + re.sub(r"[^A-Za-z0-9_-]", "_", str(base)) + ".pdf"


def _client_ip(request: Request) -> str:
    """Imzolovchining haqiqiy IP'si. Caddy reverse-proxy X-Forwarded-For qo'yadi."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return (request.client.host if request.client else "") or ""


def _sig(tur, schet, mtur, rang, profil, items):
    """накладной mazmuni imzosi — takror aniqlash uchun (izoh/kamchilik hisobga olinmaydi)."""
    norm = sorted(
        f"{it.get('kvo','')}/{it.get('shr','')}/{it.get('dln','')}/{it.get('kv2','')}"
        for it in (items or [])
    )
    raw = "|".join([str(tur or ""), str(schet or ""), str(mtur or ""),
                    str(rang or ""), str(profil or ""), "#".join(norm)])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _gen_pdf(n: dict, chat_id=None) -> bytes:
    """PDF generatsiya. FAQAT Operator-2 (OPERATORS[1]) uchun: landscape (albom) +
    sana bo'sh + kamchilik yashirin. Boshqa hamma uchun — to'liq portret nusxa."""
    op2 = config.OPERATORS[1] if len(config.OPERATORS) > 1 else 0
    clean = bool(op2) and int(chat_id or 0) == int(op2)
    return pdf.generate(n, clean=clean)


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


async def send_file(chat_id, data_bytes, filename, caption="", mime="application/pdf", reply_markup=None):
    try:
        data = {"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML"}
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                f"{API}/sendDocument", data=data,
                files={"document": (filename, data_bytes, mime)},
            )
            return r.json()
    except Exception as e:
        print("send_file() xato:", chat_id, e)
        return {"ok": False, "error": str(e)}


async def send_pdf(chat_id, pdf_bytes, filename, caption="", reply_markup=None):
    return await send_file(chat_id, pdf_bytes, filename, caption, "application/pdf", reply_markup)


def webapp_btn(text, mode, nid=None):
    url = f"{config.BASE_URL}/webapp/?v={WEBAPP_VER}&mode={mode}"
    if nid:
        url += f"&id={nid}"
    return {"inline_keyboard": [[{"text": text, "web_app": {"url": url}}]]}


async def _send_sign_req(chat_id, text, nid, btn="✍️ Ko‘rib imzolash"):
    """Imzolash so'rovini yuborib, xabar id'sini saqlaydi (imzodan keyin o'chirish uchun)."""
    r = await send_message(chat_id, text, webapp_btn(btn, "sign", nid))
    smid = ((r or {}).get("result") or {}).get("message_id")
    if smid:
        db.set_sign_msg(nid, smid)
    return r


async def _del_sign_msg(n, chat_id):
    """Imzolovchi chatidan 'Ko‘rib imzolash' xabarini o'chiradi (imzo/bekordan keyin)."""
    mid = n.get("sign_msg")
    if mid:
        try:
            await tg("deleteMessage", chat_id=chat_id, message_id=int(mid))
        except Exception:
            pass
        db.set_sign_msg(n["id"], "")


# ════════════════ initData / auth ════════════════
def validate_init_data(init_data: str) -> dict:
    # Qo'lда parse: har qiymatni unquote (parse_qsl '+' ni bo'sh joyga aylantirib hashni buzadi)
    pairs = {}
    for chunk in init_data.split("&"):
        if "=" not in chunk:
            continue
        k, v = chunk.split("=", 1)
        pairs[k] = urllib.parse.unquote(v)
    h = pairs.pop("hash", None)   # FAQAT hash chiqariladi; signature dcs'da QOLADI
    if not h:
        raise ValueError("no hash")
    dcs = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, h):
        raise ValueError("bad hash")
    return json.loads(pairs.get("user", "{}"))


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
    except Exception as e:
        print("api_me auth FAIL:", repr(e), "| initData_len:", len(body.get("initData") or ""))
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
    tur = n.get("tur")                       # ТУРни endi OTK formaда o'zi tanlaydi
    if tur not in ("alyumin", "pvh"):
        return err("Материал (тур) tanlanmagan")
    schet_w = (n.get("schet_w") or "").strip()
    schet_k = (n.get("schet_k") or "").strip()
    if not (schet_w or schet_k):
        return err("Kamida bitta Счёт (WinCAD yoki Klaes) kiriting")
    schet = " / ".join(x for x in (schet_w, schet_k) if x)
    items = n.get("items") or []
    if not items:
        return err("Kamida bitta o‘lcham kiriting")
    # Takror tekshiruvi — aynan bir xil ma'lumotli накладной bo'lsa yaratmaymiz
    new_sig = _sig(tur, schet, n.get("mtur", ""), n.get("rang", ""), n.get("profil", ""), items)
    for ex in db.by_schet_exact(schet_w, schet_k):
        if ex.get("status") == "cancelled":
            continue
        if _sig(ex.get("tur"), ex.get("schet"), ex.get("mtur"),
                ex.get("rang"), ex.get("profil"), ex.get("items")) == new_sig:
            return err(f"⚠️ Bu ma'lumotli накладной allaqachon bor (Счёт {ex.get('schet')}). Takror yaratilmadi.", 409)
    nid = db.create({
        "nomer": n.get("nomer", ""), "tur": tur, "schet": schet,
        "schet_w": schet_w, "schet_k": schet_k,
        "mtur": n.get("mtur", ""), "mahsulot": n.get("mahsulot", ""),
        "rang": n.get("rang", ""), "profil": n.get("profil", ""),
        "kamchilik": (n.get("kamchilik") or "").strip(), "items": items,
        "otk_id": uid, "otk_name": role["name"], "otk_imzo": body.get("imzo", ""),
        "otk_ip": _client_ip(request),
    })
    # Tanlangan TURга mos Master'ga xabar
    master = config.MASTER.get(tur)
    if master and master.get("id"):
        await _send_sign_req(
            master["id"],
            f"🆕 Yangi накладной <b>Счёт {schet}</b> ({pdf.TUR_LABEL.get(tur)})\n"
            f"Счёт: {schet} · {n.get('mtur','')} · {n.get('rang','')}\nTasdiqlashingiz kutilmoqda 👇",
            nid,
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
    ok, res, n2 = db.sign(nid, role["role"], uid, role["name"], body.get("imzo", ""), _client_ip(request))
    if not ok:
        return err("Navbat xato (status: " + str(res) + ")", 409)
    await _del_sign_msg(n, uid)           # imzolovchi chatidan "Ko‘rib imzolash" o'chadi
    if res == "gp":                       # Master imzoladi -> ГП ga
        await _send_sign_req(
            config.GP["id"],
            f"📨 Накладной <b>{_ref(n2)}</b> ({pdf.TUR_LABEL.get(n2['tur'])}) "
            f"Master tomonidan tasdiqlandi.\nYakuniy tasdig‘ingiz kutilmoqda 👇",
            nid,
        )
    elif res == "closed":                 # ГП imzoladi -> yopildi, PDF tarqatamiz
        await distribute_pdf(n2)
    return {"ok": True, "status": res}


@app.post("/api/cancel")
async def api_cancel(request: Request):
    """Master/ГП накладнойни bekor qiladi (OTK xato to'ldirган bo'lsa)."""
    body = await request.json()
    try:
        uid = uid_from(body)
    except Exception:
        return err("Ruxsat yo‘q", 403)
    role = config.role_of(uid)
    if not role or role["role"] not in ("master", "gp"):
        return err("Bekor qilish huquqi yo‘q", 403)
    nid = int(body["id"])
    n = db.get(nid)
    if not n:
        return err("Topilmadi", 404)
    if role["role"] == "master" and role.get("tur") != n["tur"]:
        return err("Bu sizning turingiz emas", 403)
    ok, res, n2 = db.cancel(nid, role["role"], uid, role["name"])
    if not ok:
        return err("Navbat xato (status: " + str(res) + ")", 409)
    await _del_sign_msg(n, uid)           # bekor qilgan imzolovchi chatidan xabar o'chadi
    sabab = (body.get("sabab") or "").strip()
    if n2.get("otk_id"):
        msg = (f"❌ Накладной <b>{_ref(n2)}</b> ({pdf.TUR_LABEL.get(n2['tur'])}) "
               f"{ROLE_UZ.get(role['role'])} ({role['name']}) tomonidan <b>BEKOR</b> qilindi.")
        if sabab:
            msg += f"\n📝 Sabab: {sabab}"
        msg += "\nKerak bo‘lsa yangidan yarating."
        await send_message(n2["otk_id"], msg)
    return {"ok": True, "status": "cancelled"}


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


@app.post("/api/update")
async def api_update(request: Request):
    """OTK qaytarilган накладнойни tahrirlaydi -> Master/ГП qayta imzolaydi."""
    body = await request.json()
    try:
        uid = uid_from(body)
    except Exception:
        return err("Ruxsat yo‘q", 403)
    role = config.role_of(uid)
    if not role or role["role"] != "otk":
        return err("Faqat OTK tahrirlaydi", 403)
    nid = int(body.get("id", 0))
    n = db.get(nid)
    if not n:
        return err("Topilmadi", 404)
    if n.get("otk_id") != uid:
        return err("Bu sizning накладнойngiz emas", 403)
    if n["status"] not in ("returned", "master"):
        return err("Bu holatда tahrirlab bo‘lmaydi (" + str(n["status"]) + ")", 409)
    nk = body.get("nakladnoy", {})
    tur = nk.get("tur")
    if tur not in ("alyumin", "pvh"):
        return err("Материал (тур) tanlanmagan")
    schet_w = (nk.get("schet_w") or "").strip()
    schet_k = (nk.get("schet_k") or "").strip()
    if not (schet_w or schet_k):
        return err("Kamida bitta Счёт (WinCAD yoki Klaes) kiriting")
    items = nk.get("items") or []
    if not items:
        return err("Kamida bitta o‘lcham kiriting")
    schet = " / ".join(x for x in (schet_w, schet_k) if x)
    n2 = db.update_for_edit(nid, {
        "nomer": nk.get("nomer", ""), "tur": tur, "schet": schet,
        "schet_w": schet_w, "schet_k": schet_k, "mtur": nk.get("mtur", ""),
        "mahsulot": nk.get("mahsulot", ""), "rang": nk.get("rang", ""),
        "profil": nk.get("profil", ""), "kamchilik": (nk.get("kamchilik") or "").strip(),
        "items": items, "otk_imzo": body.get("imzo", ""),
        "otk_ip": _client_ip(request),
    })
    # OTK tahrirladi -> "✏️ Tahrirlash" xabarini OTK chatidan o'chiramiz (chat tartibli qolsin)
    if n.get("edit_msg"):
        try:
            await tg("deleteMessage", chat_id=uid, message_id=int(n["edit_msg"]))
        except Exception:
            pass
        db.set_edit_msg(nid, "")
    master = config.MASTER.get(tur)
    if master and master.get("id"):
        await _send_sign_req(
            master["id"],
            f"✏️ Tuzatildi: накладной <b>{_ref(n2)}</b> ({pdf.TUR_LABEL.get(tur)})\nQayta tasdiqlang 👇",
            nid,
        )
    return {"ok": True, "id": nid}


# ════════════════ PDF tarqatish ════════════════
async def distribute_pdf(n: dict):
    fname = _fname(n)
    cap = (f"✅ <b>{_ref(n)}</b> ({pdf.TUR_LABEL.get(n.get('tur'))}) yopildi\n"
           f"{n.get('mtur','')} · {n.get('rang','')}\nTo‘g‘rimi? 👇")
    kb = {"inline_keyboard": [[
        {"text": "✅ Qabul qilindi", "callback_data": f"acc:{n['id']}"},
        {"text": "↩️ Xato — qaytarish", "callback_data": f"ret:{n['id']}"},
    ]]}
    for chat_id in config.pdf_recipients():
        if chat_id:
            # Operator-2 albom (clean) nusxa oladi, qolganlar to'liq portret
            await send_pdf(chat_id, _gen_pdf(n, chat_id), fname, cap, kb)


# ════════════════ Telegram webhook ════════════════
@app.post("/webhook")
async def webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    upd = await request.json()
    msg = upd.get("message")
    if msg:
        await on_message(msg)
    cb = upd.get("callback_query")
    if cb:
        await on_callback(cb)
    return {"ok": True}


async def on_message(msg):
    chat_id = msg["chat"]["id"]
    uid = msg["from"]["id"]
    text = (msg.get("text") or "").strip()
    role = config.role_of(uid)

    if text.startswith("/start"):
        return await on_start(uid, chat_id, role)
    if text.startswith("/hisobot"):
        if role and role["role"] in ("operator", "rahbar", "admin"):
            return await send_report_to(chat_id, _now_local().strftime("%Y-%m-%d"))
        return await send_message(chat_id, "📊 /hisobot — faqat Operator/Rahbar uchun.")
    if not role:
        return await send_message(chat_id, f"Siz ro‘yxatda yo‘qsiz.\nSizning ID: <code>{uid}</code>")
    # Har qanday boshqa matn — Счёт bo'yicha qidiruv (harf-raqam ham)
    if text and not text.startswith("/") and len(text) >= 2:
        return await do_search(chat_id, text)
    await on_start(uid, chat_id, role)


ST_UZ = {"master": "⏳ Master kutilmoqda", "gp": "⏳ ГП kutilmoqda", "closed": "✅ Yopilgan",
         "accepted": "✅ Qabul qilingan", "returned": "↩️ Qaytarilган (tuzatish kerak)",
         "cancelled": "❌ Bekor qilingan"}


async def on_callback(cb):
    """📄 PDF (har rol) · ✅ Qabul · ↩️ Qaytarish (Operator/Rahbar)."""
    cid = cb.get("id")
    uid = cb["from"]["id"]
    data = cb.get("data", "")
    m = cb.get("message") or {}
    chat_id = (m.get("chat") or {}).get("id")
    mid = m.get("message_id")
    role = config.role_of(uid)
    if not role:
        return await tg("answerCallbackQuery", callback_query_id=cid, text="Ruxsat yo‘q")

    # 🗂 O'z накладнойлари — /start spam bo'lmasin uchun tugma orqali (talab bo'yicha)
    if data == "mine":
        await tg("answerCallbackQuery", callback_query_id=cid, text="🗂 …")
        return await send_my_list(chat_id, role["role"], uid)

    # 🛡 Admin — so'nggi barcha накладнойlar
    if data == "alllist":
        if role["role"] != "admin":
            return await tg("answerCallbackQuery", callback_query_id=cid, text="Ruxsat yo‘q")
        await tg("answerCallbackQuery", callback_query_id=cid, text="🗂 …")
        return await send_recent_all(chat_id)

    try:
        action, sid = data.split(":", 1)
        nid = int(sid)
    except Exception:
        return await tg("answerCallbackQuery", callback_query_id=cid)
    n = db.get(nid)
    if not n:
        return await tg("answerCallbackQuery", callback_query_id=cid, text="Topilmadi")

    # 📄 PDF — istalган rol o'zи ko'rgan накладнойни PDF qilib oladi
    if action == "pdf":
        await tg("answerCallbackQuery", callback_query_id=cid, text="📄 PDF…")
        await send_pdf(uid, _gen_pdf(n, uid), _fname(n),
                       f"<b>{_ref(n)}</b> · {pdf.TUR_LABEL.get(n['tur'])} · {n.get('mtur','')} — {ST_UZ.get(n['status'], n['status'])}")
        return

    if role["role"] not in ("operator", "rahbar"):
        return await tg("answerCallbackQuery", callback_query_id=cid, text="Ruxsat yo‘q")
    who = cb["from"].get("first_name", "") or "xodim"
    if action == "acc":
        if n["status"] != "closed":
            return await tg("answerCallbackQuery", callback_query_id=cid, text="Allaqachon: " + ST_UZ.get(n["status"], n["status"]))
        db.set_status(nid, "accepted")                 # bazada saqlanadi
        await tg("answerCallbackQuery", callback_query_id=cid, text="✅ Qabul qilindi")
        await tg("deleteMessage", chat_id=chat_id, message_id=mid)   # chatdan o'chadi
    elif action == "ret":
        if n["status"] not in ("closed", "accepted"):
            return await tg("answerCallbackQuery", callback_query_id=cid, text="Allaqachon: " + ST_UZ.get(n["status"], n["status"]))
        db.set_status(nid, "returned")                 # bazada saqlanadi
        await tg("answerCallbackQuery", callback_query_id=cid, text="↩️ Qaytarildi — OTK tuzatadi")
        await tg("deleteMessage", chat_id=chat_id, message_id=mid)   # chatdan o'chadi
        if n.get("otk_id"):
            r = await send_message(
                n["otk_id"],
                f"↩️ Накладной <b>{_ref(n)}</b> qaytarildi ({who}).\nIltimos, to‘g‘rilang 👇",
                webapp_btn("✏️ Tahrirlash", "edit", nid),
            )
            emid = ((r or {}).get("result") or {}).get("message_id")
            if emid:
                db.set_edit_msg(nid, emid)   # OTK tahrirlagach o'chiramiz
    else:
        await tg("answerCallbackQuery", callback_query_id=cid)


def _nak_line(n):
    return (f"<b>Счёт {n.get('schet','')}</b> · {pdf.TUR_LABEL.get(n['tur'])} · "
            f"{n.get('mtur','')} — {ST_UZ.get(n['status'], n['status'])}")


async def send_my_list(chat_id, role, uid):
    """Foydalanuvchining o'z накладнойлари — har biriда 📄 PDF tugmasi (tugma orqali ochiladi)."""
    rows = db.list_by_user(role, uid, 8)
    head = "🗂 <b>O‘zingiz yaratган накладнойлар</b>" if role == "otk" else "🗂 <b>O‘zingiz imzolaган накладнойлар</b>"
    if not rows:
        return await send_message(chat_id, head + "\n\nHozircha yo‘q.")
    await send_message(chat_id, f"{head} (oxirgi {len(rows)}):")
    for n in rows:
        await send_message(chat_id, _nak_line(n),
                           {"inline_keyboard": [[{"text": "📄 PDF", "callback_data": f"pdf:{n['id']}"}]]})


async def send_recent_all(chat_id):
    """Admin — so'nggi barcha накладнойlar (har biriда 📄 PDF, holat bilan)."""
    rows = db.recent(20)
    if not rows:
        return await send_message(chat_id, "Hozircha накладной yo‘q.")
    await send_message(chat_id, f"🗂 <b>So‘nggi {len(rows)} накладной</b> (barcha holat):")
    for n in rows:
        await send_message(chat_id, _nak_line(n),
                           {"inline_keyboard": [[{"text": "📄 PDF", "callback_data": f"pdf:{n['id']}"}]]})


async def on_start(uid, chat_id, role):
    if not role:
        return await send_message(chat_id, f"👋 Salom! Siz hali ro‘yxatda yo‘qsiz.\nSizning ID: <code>{uid}</code>\nBuni administratorga bering.")
    r = role["role"]
    if r == "otk":
        create_url = f"{config.BASE_URL}/webapp/?v={WEBAPP_VER}&mode=create"
        return await send_message(
            chat_id, "👷 <b>OTK</b>\nYangi накладной yaratish yoki avval to‘ldirganlaringizni ko‘rish 👇",
            {"inline_keyboard": [
                [{"text": "➕ Накладной yaratish", "web_app": {"url": create_url}}],
                [{"text": "🗂 O‘zim to‘ldirganlarim", "callback_data": "mine"}],
            ]})
    if r in ("master", "gp"):
        pend = db.list_for_role(r, role.get("tur"))
        mine_btn = {"inline_keyboard": [[{"text": "🗂 O‘zim imzolaганларим", "callback_data": "mine"}]]}
        if pend:
            await send_message(chat_id, f"📋 <b>{ROLE_UZ[r]}</b> — tasdig‘ingiz kutilayotган {len(pend)} ta:")
            for n in pend:
                await _send_sign_req(
                    chat_id,
                    f"<b>Счёт {n['schet']}</b> · {pdf.TUR_LABEL.get(n['tur'])} · {n['mtur']} · {n['rang']}",
                    n["id"], "✍️ Imzolash")
            return await send_message(chat_id, "Avval imzolaganlaringizni ko‘rish 👇", mine_btn)
        return await send_message(chat_id, f"✅ <b>{ROLE_UZ[r]}</b> — hozircha navbatда yo‘q.", mine_btn)
    # admin — barcha ma'lumot ko'rinadi
    if r == "admin":
        return await send_message(
            chat_id,
            "🛡 <b>Admin</b> — barcha накладнойlar ko‘rinadi.\nНакладнойни topish uchun <b>Счёт raqamini</b> yuboring, yoki 👇",
            {"inline_keyboard": [[{"text": "🗂 So‘nggi накладнойlar", "callback_data": "alllist"}]]})
    # operator / rahbar
    return await send_message(chat_id, f"🔎 <b>{ROLE_UZ[r]}</b>\nНакладнойни topish uchun <b>Счёт raqamini</b> yuboring.")


def _line(n):
    return (f"<b>Счёт {n['schet']}</b> · {pdf.TUR_LABEL.get(n['tur'])} · "
            f"{n['mtur']} · {n['rang']} — {ST_UZ.get(n['status'], n['status'])}")


async def do_search(chat_id, schet):
    rows = db.search_by_schet(schet)
    if not rows:
        return await send_message(chat_id, f"🔎 Счёт «{schet}» bo‘yicha накладной topilmadi.")
    ready = [n for n in rows if n["status"] in ("closed", "accepted")]   # PDF tayyor
    others = [n for n in rows if n["status"] not in ("closed", "accepted")]
    await send_message(chat_id, f"🔎 «{schet}» — {len(rows)} ta topildi"
                       + (f", {len(ready)} ta tayyor PDF" if ready else "") + ":")
    for n in others[:15]:
        await send_message(chat_id, _line(n))
    if not ready:
        return
    if len(ready) == 1:                                  # bitta -> to'g'ridan-to'g'ri PDF
        n = ready[0]
        return await send_pdf(chat_id, _gen_pdf(n, chat_id), _fname(n), _line(n))
    # bir nechta -> bitta ZIP fayl
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        used = {}
        for n in ready:
            name = _fname(n)
            used[name] = used.get(name, 0) + 1
            if used[name] > 1:                          # bir xil nom bo'lsa — id qo'shamiz
                name = name[:-4] + f"_{n['id']}.pdf"
            z.writestr(name, _gen_pdf(n, chat_id))
    zname = "schet_" + re.sub(r"[^A-Za-z0-9_-]", "_", schet) + ".zip"
    await send_file(chat_id, buf.getvalue(), zname,
                    f"🗂 «{schet}» — <b>{len(ready)} ta</b> накладной (ZIP)", "application/zip")


# ════════════════ Kunlik hisobot (18:30) ════════════════
def _now_local():
    # Server soati. Deploy'da TZ=Asia/Tashkent bo'lsin.
    return datetime.now()


def backup_db():
    """Bazani backups/ papkasiga nusxalaydi (ma'lumot yo'qolmasligi uchun)."""
    src = db.DB_PATH
    if not os.path.exists(src):
        return
    bdir = os.path.join(os.path.dirname(os.path.abspath(src)), "backups")
    os.makedirs(bdir, exist_ok=True)
    dst = os.path.join(bdir, f"nakladnoy-{_now_local().strftime('%Y-%m-%d')}.db")
    try:
        shutil.copy2(src, dst)
        print("💾 Zaxira:", dst)
    except Exception as e:
        print("Zaxira xato:", e)


def build_report(date_str: str):
    """date_str='YYYY-MM-DD' kuni YOPILGAN накладнойlar -> (matn, ro'yxat)."""
    recs = db.closed_on(date_str)
    agg = {"alyumin": [0, 0.0], "pvh": [0, 0.0]}
    mosk = 0   # москит soni — Кв² (m²) hisobiga QO'SHILMAYDI
    for n in recs:
        if (n.get("mtur") or "").startswith("Москит"):
            mosk += 1
            continue
        t = n["tur"] if n["tur"] in agg else "alyumin"
        agg[t][0] += 1
        agg[t][1] += db.total_area(n["items"])
    a, p = agg["alyumin"], agg["pvh"]
    tot_n, tot_a = a[0] + p[0], a[1] + p[1]
    d = date_str.split("-")
    dd = f"{d[2]}.{d[1]}.{d[0]}" if len(d) == 3 else date_str
    text = (
        f"📊 <b>KUNLIK HISOBOT</b> — {dd}\n\n"
        f"🔵 Алюминь:  <b>{a[0]}</b> та · <b>{a[1]:.2f}</b> м²\n"
        f"🟣 ПВХ:      <b>{p[0]}</b> та · <b>{p[1]:.2f}</b> м²\n"
    )
    if mosk:
        text += f"🦟 Москит:   <b>{mosk}</b> та (м² hisobga olinmaydi)\n"
    text += (
        f"━━━━━━━━━━━━━\n"
        f"Σ <b>JAMI:   {tot_n} та · {tot_a:.2f} м²</b>"
    )
    text += (f"\n\n📄 Bugungi {len(recs)} та накладной PDF si quyida 👇"
             if recs else "\n\nBugun yopilган накладной bo‘lmadi.")
    return text, recs


async def send_report_to(chat_id, date_str):
    """Bitta odamга: hisobot matni + o'sha kungi barcha PDF lar."""
    text, recs = build_report(date_str)
    await send_message(chat_id, text)
    for n in recs:
        await send_pdf(chat_id, _gen_pdf(n, chat_id), _fname(n),
                       f"Счёт {n['schet']} · {pdf.TUR_LABEL.get(n['tur'])} · <b>{n.get('mtur','') or '—'}</b>")


async def send_daily_report(date_str):
    """Kunlik paketни yuborish — Operator-2 OLMAYDI (Operator-1 + Rahbar oladi)."""
    op2 = config.OPERATORS[1] if len(config.OPERATORS) > 1 else None
    for chat_id in config.pdf_recipients():
        if chat_id and chat_id != op2:
            await send_report_to(chat_id, date_str)


async def daily_report_loop():
    """Har kuni REPORT_TIME (mas. 18:30) da hisobotни yuboradi."""
    hhmm = getattr(config, "REPORT_TIME", "18:30")
    try:
        hh, mm = (int(x) for x in hhmm.split(":"))
    except Exception:
        hh, mm = 18, 30
    while True:
        now = _now_local()
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep(max(1, (target - now).total_seconds()))
        try:
            backup_db()
            await send_daily_report(_now_local().strftime("%Y-%m-%d"))
        except Exception as e:
            print("Kunlik hisobot xato:", e)


# ════════════════ Statik + startup ════════════════
@app.on_event("startup")
async def _startup():
    db.init()
    asyncio.create_task(daily_report_loop())
    print("⏰ Kunlik hisobot rejalashtirildi:", getattr(config, "REPORT_TIME", "18:30"))
    if config.BASE_URL and "example.com" not in config.BASE_URL:
        res = await tg("setWebhook", url=f"{config.BASE_URL}/webhook",
                       secret_token=WEBHOOK_SECRET,
                       allowed_updates=["message", "callback_query"])
        print("setWebhook:", res)
        await tg("setMyCommands", commands=[
            {"command": "start", "description": "Boshlash / menyu"},
            {"command": "hisobot", "description": "Bugungi kunlik hisobot"},
        ])
    else:
        print("⚠️  BASE_URL sozlanmagan — webhook o‘rnatilmadi (lokal rejim).")


_HERE = os.path.dirname(os.path.abspath(__file__))
app.mount("/webapp", StaticFiles(directory=os.path.join(_HERE, "webapp"), html=True), name="webapp")


@app.get("/")
async def root():
    return JSONResponse({"ok": True, "service": "otk-nakladnoy"})
