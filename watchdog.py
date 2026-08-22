"""
İŞKUR Bot Watchdog
Ana botun taramayı durdurup durdurmadığını kontrol eder.
Tarama 8 dakikadan fazla durursa Telegram'dan uyarı gönderir.
"""

import os
import time
import sqlite3
import logging
from datetime import datetime, timedelta

from telegram import Bot

# ─────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DB_DOSYASI       = "/home/isk73/ilanlar.db"

# Kaç dakika geçince "durdu" kabul edilsin
MAX_GECIKME_DAKIKA = 8

# Watchdog ne sıklıkla kontrol etsin (saniye)
KONTROL_ARALIGI = 180   # 3 dakika
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)


def son_calisma_zamanini_al():
    try:
        conn = sqlite3.connect(DB_DOSYASI, timeout=10)
        row = conn.execute("SELECT last_run FROM heartbeat WHERE id = 1").fetchone()
        conn.close()
        if row and row[0]:
            return datetime.fromisoformat(row[0])
        return None
    except Exception as e:
        log.error(f"DB okuma hatası: {e}")
        return None


def bildirim_gonder(mesaj: str):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mesaj)
        log.info("Bildirim gönderildi")
    except Exception as e:
        log.error(f"Bildirim hatası: {e}")


def main():
    log.info("Watchdog başlatıldı")
    uyari_gonderildi = False

    while True:
        try:
            son = son_calisma_zamanini_al()

            if son is None:
                log.warning("Henüz heartbeat kaydı yok")
            else:
                gecen = datetime.now() - son
                log.info(f"Son çalışma: {son.strftime('%H:%M:%S')} | Geçen: {gecen}")

                if gecen > timedelta(minutes=MAX_GECIKME_DAKIKA):
                    if not uyari_gonderildi:
                        bildirim_gonder(
                            f"🔴 İŞKUR botu taramayı durdurmuş görünüyor!\n"
                            f"Son çalışma: {son.strftime('%d.%m.%Y %H:%M:%S')}\n"
                            f"Geçen süre: {int(gecen.total_seconds() // 60)} dakika"
                        )
                        uyari_gonderildi = True
                else:
                    # Bot tekrar çalışmaya başladıysa bayrağı sıfırla
                    if uyari_gonderildi:
                        bildirim_gonder("🟢 İŞKUR botu tekrar çalışmaya başladı.")
                        uyari_gonderildi = False

        except Exception as e:
            log.error(f"Kontrol hatası: {e}")

        time.sleep(KONTROL_ARALIGI)


if __name__ == "__main__":
    main()
