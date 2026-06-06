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


def generate(n: dict) -> bytes:
    """накладной dict -> PDF bytes."""
    reg, bold = _font_paths()
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.add_font("doc", "", reg)
    pdf.add_font("doc", "B", bold)
    L, R = 10, 200            # chap/o'ng margin (x)
    W = R - L                 # 190 mm

    items = n.get("items", []) or []
    tur = TUR_LABEL.get(n.get("tur"), n.get("tur", ""))

    # ── Sana (o'ngда) ──
    at = n.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        dt = datetime.strptime(at[:10], "%Y-%m-%d")
        dd, mm, yy = f"{dt.day:02d}", f"{dt.month:02d}", str(dt.year)
    except Exception:
        dd, mm, yy = "  ", "  ", ""
    pdf.set_font("doc", "", 11)
    pdf.set_xy(L, 12)
    pdf.cell(W, 6, f'"{dd}" {mm} {yy} г.', align="R")

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
    pdf.cell(W * 0.6, 6, f"Счёт № {n.get('schet','')}")
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
                f"{float(it.get('kv2', 0) or 0):.2f}",
                str(it.get("izoh", "") or "")[:24],
            ]
        for (_title, w), v in zip(cols, vals):
            pdf.cell(w, 7, v, border=1, align="C")
        pdf.ln(7)

    # Итого
    tot = sum(float(i.get("kv2", 0) or 0) for i in items)
    pdf.set_x(L)
    pdf.set_font("doc", "B", 10)
    pdf.cell(cols[0][1] + cols[1][1] + cols[2][1] + cols[3][1] + cols[4][1], 7,
             "Итого:", border=1, align="R")
    pdf.cell(cols[5][1], 7, f"{tot:.2f}", border=1, align="C")
    pdf.cell(cols[6][1], 7, "", border=1)
    pdf.ln(12)

    # ── Imzolar (Мастер / ОТК / Зав.склад ГП) ──
    pdf.set_font("doc", "", 11)
    signers = [
        ("Мастер:", n.get("master_name", ""), n.get("master_imzo", "")),
        ("ОТК:", n.get("otk_name", ""), n.get("otk_imzo", "")),
        ("Зав.склад ГП:", n.get("gp_name", ""), n.get("gp_imzo", "")),
    ]
    sy = pdf.get_y()
    for role, name, imzo in signers:
        pdf.set_xy(L, sy)
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
        sy += 16

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
