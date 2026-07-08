#!/bin/bash
# Xavfsiz auto-deploy: GitHub'da o'zgarish bo'lsa tortadi -> sintaksis OK bo'lsa restart,
# xato bo'lsa eski (ishlaydigan) versiyada qoladi. Kunlik timer chaqiradi.
export PATH=/usr/bin:/bin:/usr/local/bin
set -u
APP=/home/Acer/otk-bot
LOG=/home/Acer/otk-deploy.log
cd "$APP" || exit 1

git fetch origin main --quiet 2>>"$LOG" || { echo "$(date '+%F %T') fetch xato" >>"$LOG"; exit 0; }
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0   # o'zgarish yo'q — hech narsa qilinmaydi
fi

echo "$(date '+%F %T') yangi versiya: ${REMOTE:0:7} (eski ${LOCAL:0:7})" >>"$LOG"
git reset --hard origin/main --quiet 2>>"$LOG"

if ./venv/bin/python -m py_compile server.py db.py pdf.py config.py 2>>"$LOG"; then
    sudo systemctl restart otk-bot
    echo "$(date '+%F %T') DEPLOYED ${REMOTE:0:7} -> bot qayta ishga tushdi" >>"$LOG"
else
    git reset --hard "$LOCAL" --quiet 2>>"$LOG"
    echo "$(date '+%F %T') SINTAKSIS XATO! ${LOCAL:0:7} ga qaytarildi, bot O'ZGARMADI" >>"$LOG"
fi
