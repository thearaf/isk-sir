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
    "Accept-Language": "tr-TR,tr;q=0.9",
}

# ─────────────────────────────────────────────
# FİLTRE VE YARDIMCI FONKSİYONLAR
# ─────────────────────────────────────────────
def is_valid_job_id(raw_id):
    """
    Sayı dizisinin gerçek bir ilan ID'si mi yoksa tarih/çöp veri mi olduğunu kontrol eder.
    """
    if not raw_id:
        return False
    clean = str(raw_id).strip().lstrip("0")
    if not clean or len(clean) < 6 or len(clean) > 12:
        return False
    
    # 1. YYYYMMDD Tarih Filtresi (örn: 20230320, 20240404, 20260808)
    if len(clean) == 8 and clean.startswith(("201", "202", "203")):
        return False
        
    # 2. DDMMYYYY Tarih Filtresi (örn: 04042024 -> 4042024 veya 20032023)
    if len(clean) in (7, 8) and clean.endswith(("2020", "2021", "2022", "2023", "2024", "2025", "2026")):
        return False

    return True

def id_temizle(raw_id):
    return str(raw_id).strip().lstrip("0") if raw_id else ""

def gorulmus_yukle():
    if os.path.exists(KAYIT_DOSYASI):
        try:
            with open(KAYIT_DOSYASI, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Kayıt dosyası okuma hatası: {e}")
            return {}
    return {}

def gorulmus_kaydet(veri):
    try:
        with open(KAYIT_DOSYASI, "w", encoding="utf-8") as f:
            json.dump(veri, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fdatasync(f.fileno())
    except Exception as e:
        log.error(f"Kayıt dosyası yazma hatası: {e}")

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
    except Exception as e:
        log.warning(f"ViewState hatası ({url}): {e}")
        return {}, None, None

def il_kodu_bul(soup, il_adi):
    hedef = tr_norm(il_adi)
    for sel in soup.find_all("select"):
        sel_name = (sel.get("id", "") + sel.get("name", "")).lower()
        if "il" in sel_name and "ilce" not in sel_name:
            for opt in sel.find_all("option"):
                if hedef in tr_norm(opt.text.strip()):
                    return sel.get("name") or sel.get("id"), opt.get("value", "")
    return None, None

def metin_gecerli_mi(metin):
    if not metin or len(metin.strip()) < 8: return False
    return not any(g in metin.lower() for g in GECERSIZ_METINLER)

# ─────────────────────────────────────────────
# TARAMA MODÜLLERİ
# ─────────────────────────────────────────────
def typ_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Typ/TypArama.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup: return ilanlar
        
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
                if metin_gecerli_mi(st):
                    for cand in re.findall(r'\b\d{6,12}\b', st):
                        if is_valid_job_id(cand):
                            ilanlar.append({"id": id_temizle(cand), "baslik": st[:300], "kaynak": f"TYP-{il_adi}"})
                            break
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
                if metin_gecerli_mi(st):
                    for cand in re.findall(r'\b\d{6,12}\b', st):
                        if is_valid_job_id(cand):
                            ilanlar.append({"id": id_temizle(cand), "baslik": st[:300], "kaynak": f"IUP-{il_adi}"})
                            break
    except Exception as e:
        log.warning(f"[IUP-{il_adi}] Hata: {e}")
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
                if metin_gecerli_mi(st):
                    for cand in re.findall(r'\b\d{6,12}\b', st):
                        if is_valid_job_id(cand):
                            ilanlar.append({"id": id_temizle(cand), "baslik": st[:300], "kaynak": f"Gençlik-{il_adi}"})
                            break
    except Exception as e:
        log.warning(f"[Gençlik-{il_adi}] Hata: {e}")
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
        soup2 = BeautifulSoup(r.text, "html.parser")
        
        for tablo in soup2.find_all("table"):
            for satir in tablo.find_all("tr")[1:]:
                st = satir.get_text(separator=" ", strip=True)
                if not metin_gecerli_mi(st):
                    continue
                
                ilan_no = ""
                # Öncelik 1: Tıklanabilir linklerdeki ID (a href)
                for a in satir.find_all("a"):
                    for cand in re.findall(r'\b\d{6,12}\b', a.get('href', '') + " " + a.get_text()):
                        if is_valid_job_id(cand):
                            ilan_no = id_temizle(cand)
                            break
                    if ilan_no: break
                
                # Öncelik 2: Satır içi metindeki ID
                if not ilan_no:
                    for cand in re.findall(r'\b\d{6,12}\b', st):
                        if is_valid_job_id(cand):
                            ilan_no = id_temizle(cand)
                            break

                if ilan_no:
                    ilanlar.append({"id": ilan_no, "baslik": st[:300], "kaynak": f"Açık İş-{il_adi}"})
    except Exception as e:
        log.warning(f"[Açık İş-{il_adi}] Hata: {e}")
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
                    raw_id = link["href"].split("/")[-1].split("?")[0] if link else ""
                    metin = " | ".join(h.get_text(strip=True) for h in hucreler)
                    if is_valid_job_id(raw_id) and metin_gecerli_mi(metin):
                        ilanlar.append({"id": id_temizle(raw_id), "baslik": metin[:300], "kaynak": f"Kurum Dışı-{il_adi}"})
    except Exception as e:
        log.warning(f"[Kurum Dışı-{il_adi}] Hata: {e}")
    return ilanlar

# ─────────────────────────────────────────────
# ANA ÇALIŞTIRICI (CRON JOB UYUMLU)
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

    # Aynı turda toplanan mükerrer ID'leri temizle
    tekil_döngü = []
    eklenen_id_set = set()
    for item in tum_ilanlar:
        i_id = item.get("id")
        if i_id and i_id not in eklenen_id_set:
            eklenen_id_set.add(i_id)
            tekil_döngü.append(item)

    yeni = 0
    for ilan in tekil_döngü:
        ilan_id = ilan["id"]
        if ilan_id not in gorulmus:
            # Anında RAM'e ekle
            gorulmus[ilan_id] = {
                "tarih": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "kaynak": ilan["kaynak"]
            }
            # Anında diske kaydet (Süreç aniden sonlansa bile kayıp yaşanmasın)
            gorulmus_kaydet(gorulmus)
            
            log.info(f"YENİ İLAN: {ilan_id} ({ilan['kaynak']})")
            try:
                mesaj = f"🔔 *YENİ İŞKUR İLANI*\n\n📋 *Kaynak:* {ilan['kaynak']}\n📌 *Detay:* {ilan['baslik']}"
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mesaj, parse_mode=ParseMode.MARKDOWN)
                await asyncio.sleep(1)
                yeni += 1
            except Exception as e:
                log.error(f"Bildirim atma hatası ({ilan_id}): {e}")
    
    log.info(f"İşlem tamamlandı. Yeni bulunan: {yeni} | Toplam Hafıza: {len(gorulmus)}")

if __name__ == "__main__":
    asyncio.run(main())
