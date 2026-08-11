import asyncio
import json
import os
import logging
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode

# ─────────────────────────────────────────────
# AYARLAR
# ─────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "8650054825:AAE9_yjdgQ6jujUUSFkD71_ptZaEONbON1I")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "495947944")

BASE_DIR      = "/home/isk73"
KAYIT_DOSYASI = os.path.join(BASE_DIR, "gorulmus_ilanlar.json")

# İŞKUR İl Kodları (Doğrudan İŞKUR Veritabanı ID'leri)
ILLER = [
    ("ŞIRNAK",     "73", "sirnak",     "%C5%9E%C4%B1rnak"),
    ("DİYARBAKIR", "21", "diyarbakir", "Diyarbak%C4%B1r"),
    ("MARDİN",     "47", "mardin",     "Mardin"),
    ("SİİRT",      "56", "siirt",      "Siirt"),
    ("HAKKARİ",    "30", "hakkari",    "Hakkari"),
    ("BATMAN",     "72", "batman",     "Batman"),
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9",
    "Connection": "keep-alive",
}

def is_valid_job_id(raw_id):
    if not raw_id: return False
    clean = str(raw_id).strip().lstrip("0")
    return bool(clean and 6 <= len(clean) <= 12)

def id_temizle(raw_id):
    return str(raw_id).strip().lstrip("0") if raw_id else ""

def gorulmus_yukle():
    if os.path.exists(KAYIT_DOSYASI):
        try:
            with open(KAYIT_DOSYASI, "r", encoding="utf-8") as f:
                data = json.load(f)
                log.info(f"Hafıza başarıyla yüklendi. Kayıtlı ilan sayısı: {len(data)}")
                return data
        except Exception as e:
            log.error(f"Hafıza dosyası okunamadı: {e}")
            return {}
    return {}

def gorulmus_kaydet(veri):
    gecici = KAYIT_DOSYASI + ".tmp"
    try:
        with open(gecici, "w", encoding="utf-8") as f:
            json.dump(veri, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(gecici, KAYIT_DOSYASI)
    except Exception as e:
        log.error(f"Hafıza yazma hatası: {e}")

# ─────────────────────────────────────────────
# KURUM DIŞI KAMU İŞÇİ ALIMI (GET İSTEĞİ)
# ─────────────────────────────────────────────
def kurumdisi_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    url = f"https://www.iskur.gov.tr/ilanlar/kurumdisi-kamu-isci-alim-ilanlari/?idId={il_kisa}&il={il_url}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            if "kurumdisi-kamu-isci-alim-ilanlari" in a["href"]:
                parts = a["href"].rstrip("/").split("/")
                raw_id = parts[-1].split("?")[0]
                metin = a.get_text(strip=True)
                if is_valid_job_id(raw_id) and len(metin) > 3:
                    ilanlar.append({
                        "id": id_temizle(raw_id),
                        "baslik": metin[:300],
                        "kaynak": f"Kurum Dışı Kamu-{il_adi}"
                    })
    except Exception as e:
        log.warning(f"[Kurum Dışı-{il_adi}] Hata: {e}")
    return ilanlar

# ─────────────────────────────────────────────
# AÇIK İŞ İLANLARI (POSTBACK SİMÜLASYONU)
# ─────────────────────────────────────────────
def acik_is_cek(il_adi, il_kod):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/AcikIsIlanAra.aspx"
    session = requests.Session()
    session.headers.update(HEADERS)
    
    try:
        # 1. Ana Sayfayı Çek
        r1 = session.get(url, timeout=15)
        soup1 = BeautifulSoup(r1.text, "html.parser")
        
        # Hidden input alanlarını topla
        data = {inp.get("name"): inp.get("value", "") for inp in soup1.find_all("input", {"type": "hidden"}) if inp.get("name")}
        
        # İl Seçim Parametresini ve Arama Butonunu Ayarla
        data["ctl00$ContentPlaceHolder1$ddlIl"] = il_kod
        data["ctl00$ContentPlaceHolder1$btnAra"] = "Ara"
        
        # 2. Arama POST İsteği Gönder
        session.headers.update({"Referer": url})
        r2 = session.post(url, data=data, timeout=15)
        
        # Regex ile sayfadaki tüm İlan Numaralarını Yakala
        matches = re.findall(r'IlanId=(\d+)', r2.text)
        for i_id in set(matches):
            if is_valid_job_id(i_id):
                ilanlar.append({
                    "id": id_temizle(i_id),
                    "baslik": f"{il_adi} İŞKUR Açık İş İlanı No: {i_id}",
                    "kaynak": f"Açık İş-{il_adi}"
                })
    except Exception as e:
        log.warning(f"[Açık İş-{il_adi}] Hata: {e}")
    return ilanlar

# ─────────────────────────────────────────────
# ANA DÖNGÜ
# ─────────────────────────────────────────────
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    gorulmus = gorulmus_yukle()
    tum_ilanlar = []

    for il_adi, il_kod, il_kisa, il_url in ILLER:
        tum_ilanlar += kurumdisi_cek(il_adi, il_kisa, il_url)
        tum_ilanlar += acik_is_cek(il_adi, il_kod)

    tekil_list = []
    eklenen = set()
    for item in tum_ilanlar:
        if item["id"] not in eklenen:
            eklenen.add(item["id"])
            tekil_list.append(item)

    yeni = 0
    for ilan in tekil_list:
        i_id = ilan["id"]
        if i_id not in gorulmus:
            gorulmus[i_id] = {
                "tarih": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "kaynak": ilan["kaynak"]
            }
            gorulmus_kaydet(gorulmus)
            
            try:
                mesaj = f"🔔 *YENİ İŞKUR İLANI*\n\n📋 *Kaynak:* {ilan['kaynak']}\n📌 *Detay:* {ilan['baslik']}"
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mesaj, parse_mode=ParseMode.MARKDOWN)
                await asyncio.sleep(1)
                yeni += 1
            except Exception as e:
                log.error(f"Bildirim hatası ({i_id}): {e}")

    log.info(f"İşlem tamamlandı. Yeni bildirilen: {yeni} | Toplam Hafıza: {len(gorulmus)}")

if __name__ == "__main__":
    asyncio.run(main())
