#!/bin/bash
# Xavfsiz auto-deploy: GitHub'da o'zgarish bo'lsa tortadi -> sintaksis OK va bot ko'tarilsa
# qoladi, aks holda eski (ishlaydigan) versiyaga QAYTADI.
#
# Ma'lumot xavfsizligi:
#   - nakladnoy.db va .env .gitignore da — git ularga hech qachon tegmaydi
#   - shunga qaramay har deploy oldidan bazadan izchil nusxa olinadi (oxirgi 7 tasi saqlanadi)
#   - deploydan keyin yozuvlar soni tekshiriladi, kamayib ketsa OGOHLANTIRADI
#
# root nomidan ishlaydi; git amallari Acer nomidan bajariladi.
export PATH=/usr/bin:/bin:/usr/local/bin
set -u
APP=/home/Acer/otk-bot
LOG=/home/Acer/otk-deploy.log
ZAX=/home/Acer/otk-bot/backups
cd "$APP" || exit 1

yoz() { echo "$(date '+%F %T') $*" >>"$LOG"; }
# GIT_TERMINAL_PROMPT=0 — hech qachon parol so'rab osilib qolmasin.
# credential.helper bo'sh — saqlangan kalit qidirilmasin (repo ochiq, kerak emas).
gitq() { sudo -u Acer env GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c core.askPass=true "$@"; }

# GitHub ba'zan vaqtincha javob bermaydi (so'rov cheklovi, tarmoq uzilishi).
# Shu sabab bitta urinish bilan taslim bo'lmaymiz — 3 marta urinamiz.
olindi=0
for urinish in 1 2 3; do
    if gitq fetch origin main --quiet 2>>"$LOG"; then olindi=1; break; fi
    [ "$urinish" -lt 3 ] && sleep 15
done
[ "$olindi" = 1 ] || { yoz "fetch 3 marta urinishda ham xato — o'tkazib yuborildi"; exit 0; }
LOCAL=$(gitq rev-parse HEAD)
REMOTE=$(gitq rev-parse origin/main)
[ "$LOCAL" = "$REMOTE" ] && exit 0     # o'zgarish yo'q

yoz "yangi versiya: ${REMOTE:0:7} (eski ${LOCAL:0:7})"

# ── 1) deploy oldidan baza nusxasi ──
mkdir -p "$ZAX"
SNAP="$ZAX/deploy-oldidan-$(date +%F-%H%M).db"
if sqlite3 "$APP/nakladnoy.db" ".backup $SNAP" 2>>"$LOG"; then
    chown Acer:Acer "$SNAP" 2>/dev/null
    yoz "baza nusxasi: $(basename "$SNAP")"
    ls -1t "$ZAX"/deploy-oldidan-*.db 2>/dev/null | tail -n +8 | xargs -r rm -f
else
    yoz "OGOHLANTIRISH: baza nusxasi olinmadi — deploy TO'XTATILDI"
    exit 1
fi
OLDIN=$(sqlite3 "$APP/nakladnoy.db" "select count(*) from nakladnoy;" 2>/dev/null)

# ── 2) yangi kodni tortish ──
gitq reset --hard origin/main --quiet 2>>"$LOG"

qaytar() {
    gitq reset --hard "$LOCAL" --quiet 2>>"$LOG"
    systemctl restart otk-bot
    yoz "$1 -> ${LOCAL:0:7} ga QAYTARILDI"
    exit 1
}

# ── 3) sintaksis ──
sudo -u Acer "$APP/venv/bin/python" -m py_compile server.py db.py pdf.py config.py 2>>"$LOG" \
    || qaytar "SINTAKSIS XATO"

# ── 4) qayta ishga tushirish va tekshirish ──
systemctl restart otk-bot
# Bot ishga tushishi ~7 soniya oladi (startup'da zaxira va h.k.). Avval 5 soniya kutilardi —
# sog'lom versiya ham «javob bermadi» deb qaytarilib ketardi (28-29.10.2026). Endi 60 soniyagacha kutiladi.
javob=0
for i in $(seq 1 30); do
    sleep 2
    if curl -s -o /dev/null -m 5 http://127.0.0.1:8080/; then javob=1; break; fi
done
systemctl is-active --quiet otk-bot || qaytar "BOT KO'TARILMADI"
[ "$javob" = 1 ] || qaytar "BOT JAVOB BERMADI"

KEYIN=$(sqlite3 "$APP/nakladnoy.db" "select count(*) from nakladnoy;" 2>/dev/null)
if [ -n "$OLDIN" ] && [ -n "$KEYIN" ] && [ "$KEYIN" -lt "$OLDIN" ]; then
    yoz "OGOHLANTIRISH: yozuvlar kamaydi ($OLDIN -> $KEYIN)! Nusxa: $(basename "$SNAP")"
fi
yoz "DEPLOYED ${REMOTE:0:7} — bot ishlayapti (yozuv: $KEYIN)"
