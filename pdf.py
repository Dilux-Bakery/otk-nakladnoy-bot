"""
накладной PDF generatori (fpdf2).
Qog'oz blankка o'xshash: sarlavha + jadval + 3 ta canvas-imzo (base64 PNG).

Kirill shrift kerak. Tartib bo'yicha qidiriladi:
  1) fonts/DejaVuSans.ttf  (loyiha ichida — tavsiya etiladi, har joyda ishlaydi)
  2) Windows: arial.ttf / times.ttf
  3) Linux: DejaVuSans (tizimda bo'lsa)
"""
import base64
import io
import os
from datetime import datetime
from pathlib import Path

from fpdf import FPDF

FONT_DIR = Path(__file__).parent / "fonts"

TUR_LABEL = {"alyumin": "АЛЮМИНЬ", "pvh": "ПВХ"}

# Печать (muhr) rasmi — shaffof fonли PNG. Topilsa, ГП imzolagandan keyin qo'yiladi.
STAMP_CANDIDATES = [
    Path(__file__).parent / "assets" / "pechat.png",
    Path(__file__).parent / "pechat.png",
]


def _stamp_path():
    for p in STAMP_CANDIDATES:
        if p.exists():
            return str(p)
    return None


def _font_paths():
    reg = FONT_DIR / "DejaVuSans.ttf"
    bold = FONT_DIR / "DejaVuSans-Bold.ttf"
    if reg.exists():
        return str(reg), str(bold if bold.exists() else reg)
    win = [
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/timesbd.ttf"),
    ]
    for r, b in win:
        if os.path.exists(r):
            return r, b if os.path.exists(b) else r
    lin = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if os.path.exists(lin):
        return lin, lin
    raise RuntimeError(
        "Kirill shrift topilmadi. fonts/DejaVuSans.ttf faylini qo'ying."
    )


def _decode_img(data_url):
    """data:image/png;base64,... -> BytesIO (yoki None)."""
    if not data_url:
        return None
    try:
        b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
        return io.BytesIO(base64.b64decode(b64))
    except Exception:
        return None


def generate(n: dict, clean: bool = False) -> bytes:
    """накладной dict -> PDF bytes.
    clean=True (Operator-2 uchun): portret, kontent tepada (1 listga 2 ta sig'sin) +
    sana bo'sh + kamchilik yashirin."""
    reg, bold = _font_paths()
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.add_font("doc", "", reg)
    pdf.add_font("doc", "B", bold)
    L, R = 10, 200
    W = R - L

    items = n.get("items", []) or []
    tur = TUR_LABEL.get(n.get("tur"), n.get("tur", ""))

    # ── Sana (o'ngда) ──
    at = n.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        dt = datetime.strptime(at[:10], "%Y-%m-%d")
        dd, mm, yy = f"{dt.day:02d}", f"{dt.month:02d}", str(dt.year)
    except Exception:
        dd, mm, yy = "  ", "  ", ""
    date_line = f'"____"  __________  {yy} г.' if clean else f'"{dd}" {mm} {yy} г.'
    pdf.set_font("doc", "", 11)
    pdf.set_xy(L, 12)
    pdf.cell(W, 6, date_line, align="R")

    # ── Sarlavha ──
    pdf.set_xy(L, 19)
    pdf.set_font("doc", "B", 13)
    pdf.cell(W - 40, 7, f"№ {n.get('nomer','')}   Внутренняя накладная")
    pdf.set_xy(R - 40, 19)
    pdf.set_draw_color(0)
    pdf.set_line_width(0.4)
    pdf.cell(40, 7, tur, border=1, align="C")

    # ── Счёт / Mahsulot turi ──
    pdf.set_font("doc", "", 11)
    pdf.set_xy(L, 28)
    pdf.cell(W * 0.6, 6, f"Счёт  WinCAD: {n.get('schet_w','') or '—'}   Klaes: {n.get('schet_k','') or '—'}")
    pdf.set_xy(L + W * 0.6, 28)
    pdf.cell(W * 0.4, 6, n.get("mtur", ""))

    # ── Цвет / mahsulot nomi ──
    pdf.set_xy(L, 34)
    pdf.cell(W * 0.6, 6, f"Цвет: {n.get('rang','')}")
    pdf.set_xy(L + W * 0.6, 34)
    pdf.cell(W * 0.4, 6, n.get("mahsulot", ""))

    y = 42
    if n.get("tur") == "pvh" and n.get("profil"):
        pdf.set_xy(L, y)
        pdf.cell(W, 6, f"Профил серияси: {n.get('profil')}")
        y += 7

    # ── Jadval ──
    cols = [("№", 12), ("Ед.изм", 22), ("Кол-во", 22), ("Ширина", 26),
            ("Длина", 26), ("Кв²", 24), ("Примечание", W - 132)]
    pdf.set_xy(L, y)
    pdf.set_font("doc", "B", 10)
    pdf.set_fill_color(240, 240, 240)
    for title, w in cols:
        pdf.cell(w, 8, title, border=1, align="C", fill=True)
    pdf.ln(8)

    pdf.set_font("doc", "", 10)
    rows = max(8, len(items))
    for i in range(rows):
        it = items[i] if i < len(items) else None
        pdf.set_x(L)
        vals = ["", "", "", "", "", "", ""]
        if it:
            vals = [
                str(i + 1),
                str(it.get("edizm", "") or ""),
                str(it.get("kvo", "") or ""),
                str(it.get("shr", "") or ""),
                str(it.get("dln", "") or ""),
                (f"{float(it.get('kv2')):.2f}" if it.get("kv2") else ""),
                str(it.get("izoh", "") or "")[:24],
            ]
        for (_title, w), v in zip(cols, vals):
            pdf.cell(w, 7, v, border=1, align="C")
        pdf.ln(7)

    # Итого — изделие soni + Кв² (Доп Профил bo'lsa: Кв² o'rniga umumiy uzunlik)
    tot = sum(float(i.get("kv2", 0) or 0) for i in items)
    tot_n = sum(int(float(i.get("kvo", 0) or 0)) for i in items)
    is_prof = n.get("mtur") == "Доп Профил"
    tot_len = sum(int(float(i.get("kvo", 0) or 0)) * float(i.get("dln", 0) or 0) for i in items)
    pdf.set_x(L)
    pdf.set_font("doc", "B", 10)
    pdf.cell(cols[0][1] + cols[1][1], 7, "Итого:", border=1, align="R")   # № + Ед.изм
    pdf.cell(cols[2][1], 7, str(tot_n), border=1, align="C")              # изделие soni
    pdf.cell(cols[3][1], 7, "", border=1)                                 # Ширина
    if is_prof:
        pdf.cell(cols[4][1], 7, (f"{tot_len/1000:.2f} м" if tot_len else ""), border=1, align="C")  # umumiy uzunlik
        pdf.cell(cols[5][1], 7, "", border=1)                             # Кв² bo'sh
    else:
        pdf.cell(cols[4][1], 7, "", border=1)                            # Длина
        pdf.cell(cols[5][1], 7, f"{tot:.2f}", border=1, align="C")       # Кв²
    pdf.cell(cols[6][1], 7, "", border=1)                                 # Примечание
    pdf.ln(10)

    # ── Камчилик (faqat to'liq nusxada; clean=Operator-2'да yashirin) ──
    if not clean and (n.get("kamchilik") or "").strip():
        pdf.set_font("doc", "B", 10)
        pdf.set_x(L)
        pdf.multi_cell(W, 5, f"Камчилик: {n.get('kamchilik')}")
        pdf.ln(4)

    # ── Imzolar (Мастер / ОТК / Зав.склад ГП) — IP manzil + sana bilan ──
    signers = [
        ("Мастер:", n.get("master_name", ""), n.get("master_imzo", ""), n.get("master_ip", ""), n.get("master_at", "")),
        ("ОТК:", n.get("otk_name", ""), n.get("otk_imzo", ""), n.get("otk_ip", ""), n.get("otk_at", "")),
        ("Зав.склад ГП:", n.get("gp_name", ""), n.get("gp_imzo", ""), n.get("gp_ip", ""), n.get("gp_at", "")),
    ]
    sig_top = pdf.get_y()
    sy = sig_top
    for role, name, imzo, ip, at in signers:
        pdf.set_xy(L, sy)
        pdf.set_font("doc", "", 11)
        pdf.cell(48, 8, f"{role} {name}")
        img = _decode_img(imzo)
        if img:
            try:
                pdf.image(img, x=L + 70, y=sy - 4, h=12)
            except Exception:
                pass
        pdf.set_draw_color(0)
        pdf.set_line_width(0.3)
        pdf.line(L + 60, sy + 8, R, sy + 8)   # imzo chizig'i
        # IP manzil (+ sana; clean rejimда sanasiz)
        if ip:
            info = f"IP: {ip}"
            if at and not clean:
                info += f"   {at}"
            pdf.set_xy(L, sy + 8.4)
            pdf.set_font("doc", "", 7)
            pdf.set_text_color(110, 110, 110)
            pdf.cell(70, 4, info)
            pdf.set_text_color(0, 0, 0)
        sy += 16

    # ── Печать (muhr) — ГП yopgandan keyin, fayl bo'lsa imzolar ustiga joylanadi ──
    stamp = _stamp_path()
    if stamp and n.get("gp_imzo"):
        try:
            sw = 40                                  # muhr o'lchami (mm)
            pdf.image(stamp, x=R - sw - 2, y=sig_top + 4, w=sw)
        except Exception:
            pass

    out = pdf.output()
    return bytes(out)


if __name__ == "__main__":
    # Namuna PDF (test)
    import base64 as _b64
    # 1x1 shaffof PNG (imzo o'rnига namuna)
    px = _b64.b64encode(_b64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )).decode()
    sample = {
        "nomer": "422", "tur": "alyumin", "schet": "7107964",
        "mtur": "Дверь", "mahsulot": "Профиль 60мм", "rang": "Солодовый дуб",
        "items": [{"edizm": "шт", "kvo": 1, "shr": 748, "dln": 2350, "kv2": 1.76, "izoh": ""}],
        "otk_name": "Нажмитдинов А.", "otk_imzo": "data:image/png;base64," + px,
        "master_name": "Мамаджанов А.", "master_imzo": "data:image/png;base64," + px,
        "gp_name": "Нематуллаев Э.", "gp_imzo": "data:image/png;base64," + px,
        "created_at": "2026-06-04 10:00",
    }
    data = generate(sample)
    Path("namuna.pdf").write_bytes(data)
    print("namuna.pdf yozildi:", len(data), "bayt")
