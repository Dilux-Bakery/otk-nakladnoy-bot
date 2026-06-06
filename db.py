"""
SQLite baza — накладнойlar va imzolar.

Status oqimi:  'master'  ->  'gp'  ->  'closed'
  - OTK yaratadi+imzolaydi   -> status 'master'  (Master kutilmoqda)
  - Master imzolaydi         -> status 'gp'      (ГП kutilmoqda)
  - ГП imzolaydi             -> status 'closed'  (yopildi, PDF tarqatiladi)
"""
import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

DB_PATH = os.environ.get("NAKLADNOY_DB", str(Path(__file__).parent / "nakladnoy.db"))

# status -> keyingi rol (kim imzolashi kerak)
NEXT_SIGNER = {"master": "master", "gp": "gp"}
# rol imzolagandan keyingi status
AFTER_SIGN = {"master": "gp", "gp": "closed"}


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def init():
    with _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS nakladnoy(
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            nomer      TEXT,
            tur        TEXT,                 -- 'alyumin' | 'pvh'
            schet      TEXT,
            mtur       TEXT,                 -- Дверь/Окно
            mahsulot   TEXT,
            rang       TEXT,
            profil     TEXT,
            items      TEXT,                 -- JSON ro'yxat
            status     TEXT DEFAULT 'master',
            otk_id     INTEGER, otk_name    TEXT, otk_imzo    TEXT, otk_at    TEXT,
            master_id  INTEGER, master_name TEXT, master_imzo TEXT, master_at TEXT,
            gp_id      INTEGER, gp_name      TEXT, gp_imzo     TEXT, gp_at     TEXT,
            created_at TEXT
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_schet ON nakladnoy(schet)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_status ON nakladnoy(status)")


def _row(r):
    if r is None:
        return None
    d = dict(r)
    d["items"] = json.loads(d.get("items") or "[]")
    return d


def create(d: dict) -> int:
    """OTK yangi накладной yaratadi (imzo bilan). id qaytaradi."""
    now = _now()
    with _conn() as c:
        cur = c.execute("""
            INSERT INTO nakladnoy
              (nomer,tur,schet,mtur,mahsulot,rang,profil,items,status,
               otk_id,otk_name,otk_imzo,otk_at,created_at)
            VALUES (?,?,?,?,?,?,?,?,'master',?,?,?,?,?)
        """, (
            d.get("nomer", ""), d.get("tur", "alyumin"), d.get("schet", ""),
            d.get("mtur", ""), d.get("mahsulot", ""), d.get("rang", ""),
            d.get("profil", ""), json.dumps(d.get("items", []), ensure_ascii=False),
            d.get("otk_id"), d.get("otk_name", ""), d.get("otk_imzo", ""), now, now,
        ))
        return cur.lastrowid


def get(nid: int):
    with _conn() as c:
        return _row(c.execute("SELECT * FROM nakladnoy WHERE id=?", (nid,)).fetchone())


def sign(nid: int, role: str, uid: int, name: str, imzo: str):
    """
    Master yoki ГП imzolaydi. Status tartibini tekshiradi.
    Qaytadi: (ok: bool, xabar/yangi_status, nakladnoy_dict|None)
    """
    n = get(nid)
    if not n:
        return False, "not_found", None
    if role not in ("master", "gp"):
        return False, "bad_role", None
    if n["status"] != role:
        # navbat emas (masalan ГП hali Master imzolamasdan kirsa)
        return False, f"wrong_status:{n['status']}", n
    new_status = AFTER_SIGN[role]
    now = _now()
    with _conn() as c:
        c.execute(
            f"UPDATE nakladnoy SET {role}_id=?, {role}_name=?, {role}_imzo=?, "
            f"{role}_at=?, status=? WHERE id=?",
            (uid, name, imzo, now, new_status, nid),
        )
    return True, new_status, get(nid)


def search_by_schet(schet: str, limit: int = 50):
    """Счёт raqami bo'yicha (qisman moslik) qidiruv — yangi tartibда."""
    schet = (schet or "").strip()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM nakladnoy WHERE schet LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{schet}%", limit),
        ).fetchall()
    return [_row(r) for r in rows]


def list_for_role(role: str, tur: str = None, limit: int = 50):
    """Berilgan rol uchun navbatda turган накладнойlar (Master/ГП)."""
    with _conn() as c:
        if role == "gp":
            rows = c.execute(
                "SELECT * FROM nakladnoy WHERE status='gp' ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        elif role == "master":
            rows = c.execute(
                "SELECT * FROM nakladnoy WHERE status='master' AND tur=? ORDER BY id DESC LIMIT ?",
                (tur, limit),
            ).fetchall()
        else:
            rows = []
    return [_row(r) for r in rows]


def recent(limit: int = 30):
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM nakladnoy ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row(r) for r in rows]


def closed_on(date_str: str):
    """Berilgan kunda YOPILGAN накладнойlar (gp_at sanasi bo'yicha)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM nakladnoy WHERE status='closed' AND substr(gp_at,1,10)=? ORDER BY id",
            (date_str,),
        ).fetchall()
    return [_row(r) for r in rows]


def total_area(items):
    return round(sum(float(i.get("kv2", 0) or 0) for i in items), 4)


if __name__ == "__main__":
    init()
    print("DB tayyor:", DB_PATH)
