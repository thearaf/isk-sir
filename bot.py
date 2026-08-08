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
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─────────────────────────────────────────────
# YARDIMCI FONKSİYONLAR
# ─────────────────────────────────────────────
def gorulmus_yukle():
    if os.path.exists(KAYIT_DOSYASI):
        try:
            with open(KAYIT_DOSYASI, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def gorulmus_kaydet(veri):
    with open(KAYIT_DOSYASI, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fdatasync(f.fileno())

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
        r = session.get(url, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        data = {inp.get("name"): inp.get("value", "") for inp in soup.find_all("input", {"type": "hidden"}) if inp.get("name")}
        return data, soup, r.cookies
    except: return {}, None, None

def il_kodu_bul(soup, il_adi):
    hedef = tr_norm(il_adi)
    for sel in soup.find_all("select"):
        if "il" in (sel.get("id", "") + sel.get("name", "")).lower() and "ilce" not in (sel.get("id", "") + sel.get("name", "")).lower():
            for opt in sel.find_all("option"):
                if hedef in tr_norm(opt.text.strip()):
                    return sel.get("name") or sel.get("id"), opt.get("value", "")
    return None, None

def metin_gecerli_mi(metin):
    if not metin or len(metin.strip()) < 8: return False
    return not any(g in metin.lower() for g in GECERSIZ_METINLER)

def id_temizle(raw_id):
    return str(raw_id).strip().lstrip("0") if raw_id else ""

# ─────────────────────────────────────────────
# TARAMA FONKSİYONLARI (Kısaltıldı, mantık aynı)
# ─────────────────────────────────────────────
def typ_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Typ/TypArama.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup: return ilanlar
        
        # İl seçimi
        for sel in soup.find_all("select"):
            for opt in sel.find_all("option"):
                if tr_norm(il_adi) in tr_norm(opt.text.strip()):
                    data[sel.get("name") or sel.get("id")] = opt.get("value", "")
        
        data["__EVENTTARGET"] = "ctl05$ctlCommandTypKayit$CommandItem_Search"
        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")

        for tablo in soup2.find_all("table"):
            for satir in tablo.find_all("tr")[1:]:
                st = satir.get_text(separator=" ", strip=True)
                m = re.search(r'\b\d{6,12}\b', st)
                if m and metin_gecerli_mi(st):
                    ilanlar.append({"id": id_temizle(m.group(0)), "baslik": st[:400], "kaynak": f"TYP-{il_adi}"})
    except: pass
    return ilanlar

def iup_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/IstIupArama.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup: return ilanlar
        
        for sel in soup.find_all("select"):
            for opt in sel.find_all("option"):
                if tr_norm(il_adi) in tr_norm(opt.text.strip()):
                    data[sel.get("name") or sel.get("id")] = opt.get("value", "")
        
        data["__EVENTTARGET"] = "ctl05$ctlCommandIupKayit$CommandItem_Search"
        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")
        
        for tablo in soup2.find_all("table"):
            for satir in tablo.find_all("tr")[1:]:
                st = satir.get_text(separator=" ", strip=True)
                m = re.search(r'\b\d{6,12}\b', st)
                if m and metin_gecerli_mi(st):
                    ilanlar.append({"id": id_temizle(m.group(0)), "baslik": st[:400], "kaynak": f"IUP-{il_adi}"})
    except: pass
    return ilanlar

def genclik_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/IstIskurGenclikProgramArama.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup: return ilanlar
        il_field, il_val = il_kodu_bul(soup, il_adi)
        if il_field: data[il_field] = il_val
        data["__EVENTTARGET"] = "ctl05$ctlCommandGenclikKayit$CommandItem_Search"
        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")
        for tablo in soup2.find_all("table"):
            for satir in tablo.find_all("tr")[1:]:
                st = satir.get_text(separator=" ", strip=True)
                m = re.search(r'\b\d{6,12}\b', st)
                if m and metin_gecerli_mi(st):
                    ilanlar.append({"id": id_temizle(m.group(0)), "baslik": st[:400], "kaynak": f"Gençlik-{il_adi}"})
    except: pass
    return ilanlar

def acik_is_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/AcikIsIlanAra.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup: return ilanlar
        il_field, il_val = il_kodu_bul(soup, il_adi)
        if il_field: data[il_field] = il_val
        for rad in soup.find_all("input", {"type": "radio"}):
            if "isyeri" in rad.get("name", "").lower(): data[rad.get("name")] = "1"
        data["__EVENTTARGET"] = "ctl04$ctlAcikIsPageCommand_CommandItem_Search"
        r = session.post(url, data=data, timeout=15, cookies=cookies)
        html = r.text
        nums = set(re.findall(r'\b0*\d{7,10}\b', html))
        for num in nums:
            if metin_gecerli_mi(html):
                ilanlar.append({"id": id_temizle(num), "baslik": "Açık İş İlanı", "kaynak": f"Açık İş-{il_adi}"})
    except: pass
    return ilanlar

def kurumdisi_cek(il_adi, il_kisa, il_url):
    ilanlar = []
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
                    ilan_id = id_temizle(link["href"].split("/")[-1].split("?")[0]) if link else ""
                    metin = " | ".join(h.get_text(strip=True) for h in hucreler)
                    if ilan_id and metin_gecerli_mi(metin):
                        ilanlar.append({"id": ilan_id, "baslik": metin[:400], "kaynak": f"Kurum Dışı-{il_adi}"})
    except: pass
    return ilanlar

# ─────────────────────────────────────────────
# ANA ÇALIŞTIRICI
# ─────────────────────────────────────────────
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    gorulmus = gorulmus_yukle()
    tum_ilanlar = []
    
    for il_adi, il_kisa, il_url in ILLER:
        tum_ilanlar += typ_cek(il_adi, il_kisa, il_url)
        tum_ilanlar += iup_cek(il_adi, il_kisa, il_url)
        tum_ilanlar += genclik_cek(il_adi, il_kisa, il_url)
        tum_ilanlar += acik_is_cek(il_adi, il_kisa, il_url)
        tum_ilanlar += kurumdisi_cek(il_adi, il_kisa, il_url)

    yeni = 0
    for ilan in tum_ilanlar:
        if ilan["id"] not in gorulmus:
            gorulmus[ilan["id"]] = {"tarih": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            log.info(f"YENİ İLAN: {ilan['id']} ({ilan['kaynak']})")
            try:
                mesaj = f"🔔 *YENİ İŞKUR İLANI*\n\n📋 *Kaynak:* {ilan['kaynak']}\n📌 *Detay:* {ilan['baslik']}"
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mesaj, parse_mode=ParseMode.MARKDOWN)
                await asyncio.sleep(1)
                yeni += 1
            except Exception as e:
                log.error(f"Bildirim hatası: {e}")
    
    gorulmus_kaydet(gorulmus)
    log.info(f"İşlem tamamlandı. Yeni bulunan: {yeni}")

if __name__ == "__main__":
    asyncio.run(main())
