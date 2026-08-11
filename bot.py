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

ILLER = [
    ("ŞIRNAK",     "sirnak",     "%C5%9E%C4%B1rnak"),
    ("DİYARBAKIR", "diyarbakir", "Diyarbak%C4%B1r"),
    ("MARDİN",     "mardin",     "Mardin"),
    ("SİİRT",      "siirt",      "Siirt"),
    ("HAKKARİ",    "hakkari",    "Hakkari"),
    ("BATMAN",     "batman",     "Batman"),
]

GECERSIZ_METINLER = [
    "kayıt bulunamamıştır", "kayit bulunamamistir", "sonuç bulunamadı", 
    "sonuc bulunamadi", "veri bulunamadı", "arama kriterlerinize"
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://esube.iskur.gov.tr",
    "Connection": "keep-alive",
}

# ─────────────────────────────────────────────
# YARDIMCI FONKSİYONLAR
# ─────────────────────────────────────────────
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

def tr_norm(metin):
    if not metin: return ""
    res = metin.upper()
    for tr, en in [("i","I"), ("İ","I"), ("ı","I"), ("ş","S"), ("Ş","S"), ("ğ","G"), ("Ğ","G"), ("ü","U"), ("Ü","U"), ("ö","O"), ("Ö","O"), ("ç","C"), ("Ç","C")]:
        res = res.replace(tr, en)
    return res

def session_ac():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s

def viewstate_al(session, url):
    try:
        session.headers.update({"Referer": url})
        r = session.get(url, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        data = {inp.get("name"): inp.get("value", "") for inp in soup.find_all("input", {"type": "hidden"}) if inp.get("name")}
        return data, soup, r.cookies
    except Exception as e:
        log.warning(f"ViewState hatası ({url}): {e}")
        return {}, None, None

def il_kodu_bul(soup, il_adi):
    hedef = tr_norm(il_adi)
    for sel in soup.find_all("select"):
        sel_name = sel.get("name", "")
        # İŞKUR'da il dropdown alanı genelde 'ddlIl' veya 'drpIl' içerir
        if "il" in sel_name.lower() and "ilce" not in sel_name.lower():
            for opt in sel.find_all("option"):
                if hedef in tr_norm(opt.text.strip()):
                    return sel_name, opt.get("value", "")
    return None, None

def metin_gecerli_mi(metin):
    if not metin or len(metin.strip()) < 8: return False
    return not any(g in metin.lower() for g in GECERSIZ_METINLER)

# ─────────────────────────────────────────────
# TARAMA MODÜLLERİ
# ─────────────────────────────────────────────
def acik_is_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/AcikIsIlanAra.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup: return ilanlar

        il_field, il_val = il_kodu_bul(soup, il_adi)
        if il_field and il_val:
            data[il_field] = il_val
        
        # Arama butonunu tetikleme
        btn = soup.find("input", {"type": "submit", "value": lambda v: v and "ARA" in v.upper()})
        if btn and btn.get("name"):
            data[btn.get("name")] = btn.get("value", "Ara")
        else:
            data["__EVENTTARGET"] = "ctl04$ctlAcikIsPageCommand_CommandItem_Search"

        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")

        for tablo in soup2.find_all("table"):
            for satir in tablo.find_all("tr")[1:]:
                hucreler = satir.find_all("td")
                if not hucreler: continue
                st = satir.get_text(separator=" ", strip=True)
                if not metin_gecerli_mi(st): continue

                ilan_no = ""
                link = satir.find("a", href=True)
                if link:
                    m = re.search(r'\b\d{6,12}\b', link['href'] + " " + link.get_text())
                    if m and is_valid_job_id(m.group(0)):
                        ilan_no = id_temizle(m.group(0))

                if not ilan_no and len(hucreler) >= 2:
                    m = re.search(r'\b\d{6,12}\b', hucreler[0].get_text() + " " + hucreler[1].get_text())
                    if m and is_valid_job_id(m.group(0)):
                        ilan_no = id_temizle(m.group(0))

                if ilan_no:
                    ilanlar.append({"id": ilan_no, "baslik": st[:300], "kaynak": f"Açık İş-{il_adi}"})
    except Exception as e:
        log.warning(f"[Açık İş-{il_adi}] Hata: {e}")
    return ilanlar

def kurumdisi_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    # Kurum dışı ilanlar ASP.NET yerine doğrudan GET URL parametresiyle çalışır
    url = f"https://www.iskur.gov.tr/ilanlar/kurumdisi-kamu-isci-alim-ilanlari/?idId={il_kisa}&il={il_url}"
    try:
        session = session_ac()
        r = session.get(url, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for tablo in soup.find_all("table"):
            for satir in tablo.find_all("tr")[1:]:
                hucreler = satir.find_all("td")
                if len(hucreler) >= 2:
                    link = satir.find("a", href=True)
                    raw_id = link["href"].split("/")[-1].split("?")[0] if link else ""
                    metin = " | ".join(h.get_text(strip=True) for h in hucreler)
                    if is_valid_job_id(raw_id) and metin_gecerli_mi(metin):
                        ilanlar.append({"id": id_temizle(raw_id), "baslik": metin[:300], "kaynak": f"Kurum Dışı-{il_adi}"})
    except Exception as e:
        log.warning(f"[Kurum Dışı-{il_adi}] Hata: {e}")
    return ilanlar

def typ_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Typ/TypArama.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup: return ilanlar
        il_field, il_val = il_kodu_bul(soup, il_adi)
        if il_field and il_val: data[il_field] = il_val
        data["__EVENTTARGET"] = "ctl05$ctlCommandTypKayit$CommandItem_Search"
        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")
        for tablo in soup2.find_all("table"):
            for satir in tablo.find_all("tr")[1:]:
                st = satir.get_text(separator=" ", strip=True)
                if metin_gecerli_mi(st):
                    link = satir.find("a", href=True)
                    if link:
                        m = re.search(r'\b\d{6,12}\b', link['href'] + " " + link.get_text())
                        if m and is_valid_job_id(m.group(0)):
                            ilanlar.append({"id": id_temizle(m.group(0)), "baslik": st[:300], "kaynak": f"TYP-{il_adi}"})
    except Exception as e:
        log.warning(f"[TYP-{il_adi}] Hata: {e}")
    return ilanlar

def iup_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/IstIupArama.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup: return ilanlar
        il_field, il_val = il_kodu_bul(soup, il_adi)
        if il_field and il_val: data[il_field] = il_val
        data["__EVENTTARGET"] = "ctl05$ctlCommandIupKayit$CommandItem_Search"
        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")
        for tablo in soup2.find_all("table"):
            for satir in tablo.find_all("tr")[1:]:
                st = satir.get_text(separator=" ", strip=True)
                if metin_gecerli_mi(st):
                    link = satir.find("a", href=True)
                    if link:
                        m = re.search(r'\b\d{6,12}\b', link['href'] + " " + link.get_text())
                        if m and is_valid_job_id(m.group(0)):
                            ilanlar.append({"id": id_temizle(m.group(0)), "baslik": st[:300], "kaynak": f"IUP-{il_adi}"})
    except Exception as e:
        log.warning(f"[IUP-{il_adi}] Hata: {e}")
    return ilanlar

# ─────────────────────────────────────────────
# ANA DÖNGÜ
# ─────────────────────────────────────────────
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    gorulmus = gorulmus_yukle()
    tum_ilanlar = []

    for il_adi, il_kisa, il_url in ILLER:
        tum_ilanlar += acik_is_cek(il_adi, il_kisa, il_url)
        tum_ilanlar += kurumdisi_cek(il_adi, il_kisa, il_url)
        tum_ilanlar += typ_cek(il_adi, il_kisa, il_url)
        tum_ilanlar += iup_cek(il_adi, il_kisa, il_url)

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
