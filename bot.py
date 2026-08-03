"""
İŞKUR Çok İl İlan Takip Botu
Şırnak, Diyarbakır, Mardin, Siirt, Hakkari, Batman
"""

import asyncio
import json
import os
import logging
import hashlib
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode

# ─────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
KONTROL_SURESI   = 30

# Dosya yolunu bot.py ile aynı klasöre dinamik olarak bağlar
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
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def gorulmus_yukle():
    if os.path.exists(KAYIT_DOSYASI):
        try:
            with open(KAYIT_DOSYASI, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Kayıt dosyası okunurken hata: {e}")
            return {}
    return {}


def gorulmus_kaydet(veri):
    try:
        with open(KAYIT_DOSYASI, "w", encoding="utf-8") as f:
            json.dump(veri, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())  # Veriyi anında diske yazmaya zorlar
    except Exception as e:
        log.error(f"Kayıt dosyasına yazılırken hata: {e}")


def kisa_hash(metin):
    temiz_metin = "".join(metin.split())
    return hashlib.md5(temiz_metin.encode('utf-8')).hexdigest()[:12]


def tr_norm(metin):
    """Türkçe karakterleri büyük harf uyumlu hale getirir"""
    if not metin:
        return ""
    replacements = [
        ("i", "I"), ("İ", "I"), ("ı", "I"),
        ("ş", "S"), ("Ş", "S"),
        ("ğ", "G"), ("Ğ", "G"),
        ("ü", "U"), ("Ü", "U"),
        ("ö", "O"), ("Ö", "O"),
        ("ç", "C"), ("Ç", "C")
    ]
    res = metin.upper()
    for tr, en in replacements:
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
        data = {}
        for inp in soup.find_all("input", {"type": "hidden"}):
            name = inp.get("name")
            if name:
                data[name] = inp.get("value", "")
        return data, soup, r.cookies
    except Exception as e:
        log.warning(f"ViewState alınamadı: {e}")
        return {}, None, None


def il_kodu_bul(soup, il_adi):
    hedef = tr_norm(il_adi)
    for sel in soup.find_all("select"):
        sel_id = sel.get("id", "") + sel.get("name", "")
        if "il" in sel_id.lower() and "ilce" not in sel_id.lower():
            for opt in sel.find_all("option"):
                if hedef in tr_norm(opt.text.strip()):
                    return sel.get("name") or sel.get("id"), opt.get("value", "")
    return None, None


def grid_satirlari_oku(soup, kaynak):
    ilanlar = []
    for tablo in soup.find_all("table"):
        tablo_id = tablo.get("id", "")
        if "grid" not in tablo_id.lower() and "Grid" not in tablo_id:
            continue
        satirlar = tablo.find_all("tr")
        if len(satirlar) < 2:
            continue
        for satir in satirlar[1:]:
            hucreler = satir.find_all("td")
            if len(hucreler) < 2:
                continue
            metin = " | ".join(h.get_text(strip=True) for h in hucreler if h.get_text(strip=True))
            if metin and len(metin) > 5:
                ilan_id = hucreler[0].get_text(strip=True)
                if not ilan_id or len(ilan_id) < 2:
                    ilan_id = kisa_hash(metin)
                
                ilanlar.append({
                    "id": ilan_id,
                    "baslik": metin[:400],
                    "kaynak": kaynak
                })
    return ilanlar


def ara_buton_adi(soup):
    for inp in soup.find_all("input", {"type": ["submit", "button", "image"]}):
        val = inp.get("value", "")
        name = inp.get("name", "")
        if "Ara" in val or "Search" in name or "Ara" in name:
            return name
    return None


# ──────────────────────────────────────────────────────
# 1) TYP — her il için (Güncellenmiş & Güçlendirilmiş)
# ──────────────────────────────────────────────────────
def typ_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Typ/TypArama.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup:
            return ilanlar

        hedef_il = tr_norm(il_adi)
        for sel in soup.find_all("select"):
            for opt in sel.find_all("option"):
                if hedef_il in tr_norm(opt.text.strip()):
                    field_name = sel.get("name") or sel.get("id")
                    if field_name:
                        data[field_name] = opt.get("value", "")
                    break

        data["__EVENTTARGET"] = "ctl05$ctlCommandTypKayit$CommandItem_Search"
        data["__EVENTARGUMENT"] = ""

        btn_name = ara_buton_adi(soup)
        if btn_name:
            data[btn_name] = "Ara"

        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")

        GECERSIZ = {"ara", "temizle", "ara | temizle", "search", "reset", "sec", "seç", ""}
        for tablo in soup2.find_all("table"):
            satirlar = tablo.find_all("tr")
            if len(satirlar) < 2:
                continue
            for satir in satirlar[1:]:
                hucreler = satir.find_all("td")
                if len(hucreler) < 2:
                    continue
                
                ilan_no = ""
                for hucre in hucreler:
                    val = hucre.get_text(strip=True)
                    if val.isdigit() and len(val) >= 4:
                        ilan_no = val
                        break
                
                metin = " | ".join(h.get_text(strip=True) for h in hucreler if h.get_text(strip=True) and h.get_text(strip=True).lower() not in GECERSIZ)
                
                if metin and len(metin) > 10:
                    if not ilan_no:
                        ilan_no = kisa_hash(metin)
                    
                    ilanlar.append({
                        "id": ilan_no,
                        "baslik": metin[:400],
                        "kaynak": f"TYP-{il_adi}"
                    })

        log.info(f"[TYP-{il_adi}] {len(ilanlar)} ilan")
    except Exception as e:
        log.warning(f"[TYP-{il_adi}] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 2) IUP — her il için
# ──────────────────────────────────────────────────────
def iup_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/IstIupArama.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup:
            return ilanlar

        hedef_il = tr_norm(il_adi)
        for sel in soup.find_all("select"):
            for opt in sel.find_all("option"):
                if hedef_il in tr_norm(opt.text.strip()):
                    field_name = sel.get("name") or sel.get("id")
                    if field_name:
                        data[field_name] = opt.get("value", "")
                    break

        for sel in soup.find_all("select"):
            for opt in sel.find_all("option"):
                if "İUP" in opt.text.upper() or "IUP" in opt.text.upper():
                    field_name = sel.get("name") or sel.get("id")
                    if field_name:
                        data[field_name] = opt.get("value", "")
                    break

        data["__EVENTTARGET"] = "ctl05$ctlCommandIupKayit$CommandItem_Search"
        data["__EVENTARGUMENT"] = ""

        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")

        GECERSIZ = {"ara", "temizle", "ara | temizle", "search", "reset", "sec", "seç", ""}
        for tablo in soup2.find_all("table"):
            satirlar = tablo.find_all("tr")
            if len(satirlar) < 2:
                continue
            for satir in satirlar[1:]:
                hucreler = satir.find_all("td")
                if len(hucreler) < 2:
                    continue
                ilan_no = ""
                for hucre in hucreler:
                    val = hucre.get_text(strip=True)
                    if val.isdigit() and len(val) >= 4:
                        ilan_no = val
                        break
                if not ilan_no:
                    continue
                metin = " | ".join(h.get_text(strip=True) for h in hucreler if h.get_text(strip=True) and h.get_text(strip=True).lower() not in GECERSIZ)
                if metin:
                    ilanlar.append({
                        "id": ilan_no,
                        "baslik": metin[:400],
                        "kaynak": f"IUP-{il_adi}"
                    })
        log.info(f"[IUP-{il_adi}] {len(ilanlar)} ilan")
    except Exception as e:
        log.warning(f"[IUP-{il_adi}] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 3) Gençlik — her il için
# ──────────────────────────────────────────────────────
def genclik_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/IstIskurGenclikProgramArama.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup:
            return ilanlar

        il_field, il_val = il_kodu_bul(soup, il_adi)
        if il_field:
            data[il_field] = il_val

        btn = ara_buton_adi(soup)
        if btn:
            data[btn] = "Ara"

        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")
        ilanlar = grid_satirlari_oku(soup2, f"Gençlik-{il_adi}")
        log.info(f"[Gençlik-{il_adi}] {len(ilanlar)} ilan")
    except Exception as e:
        log.warning(f"[Gençlik-{il_adi}] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 4) Açık İş (Kamu) — her il için
# ──────────────────────────────────────────────────────
def acik_is_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/AcikIsIlanAra.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup:
            return ilanlar

        for inp in soup.find_all("input", {"type": "radio"}):
            label = inp.find_next("label")
            label_text = label.get_text(strip=True) if label else ""
            if "Kamu" in label_text or "KAMU" in label_text:
                data[inp.get("name")] = inp.get("value", "")
                break

        il_field, il_val = il_kodu_bul(soup, il_adi)
        if il_field:
            data[il_field] = il_val

        btn = ara_buton_adi(soup)
        if btn:
            data[btn] = "Ara"

        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")
        ilanlar = grid_satirlari_oku(soup2, f"Açık İş (Kamu)-{il_adi}")
        log.info(f"[Açık İş-{il_adi}] {len(ilanlar)} ilan")
    except Exception as e:
        log.warning(f"[Açık İş-{il_adi}] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 5) Kurum Dışı Kamu — her il için
# ──────────────────────────────────────────────────────
def kurumdisi_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    url = f"https://www.iskur.gov.tr/ilanlar/kurumdisi-kamu-isci-alim-ilanlari/?idId={il_kisa}&il={il_url}"
    try:
        session = session_ac()
        r = session.get(url, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        for tablo in soup.find_all("table"):
            satirlar = tablo.find_all("tr")
            if len(satirlar) < 2:
                continue
            baslik = satirlar[0].get_text(strip=True).upper()
            if any(k in baslik for k in ["İLAN", "KURUM", "TARİH", "BAŞVURU", "NO"]):
                for satir in satirlar[1:]:
                    hucreler = satir.find_all("td")
                    if len(hucreler) >= 2:
                        metin = " | ".join(h.get_text(strip=True) for h in hucreler if h.get_text(strip=True))
                        if metin:
                            ilan_id = hucreler[0].get_text(strip=True)
                            if not ilan_id or len(ilan_id) < 2:
                                ilan_id = kisa_hash(metin)
                            
                            ilanlar.append({
                                "id": ilan_id,
                                "baslik": metin[:400],
                                "kaynak": f"Kurum Dışı-{il_adi}"
                            })
                break

        if not ilanlar:
            for css in ["article", ".list-item", ".ilan-item"]:
                for el in soup.select(css):
                    metin = el.get_text(strip=True)
                    if metin and len(metin) > 20:
                        ilanlar.append({
                            "id": kisa_hash(metin),
                            "baslik": metin[:400],
                            "kaynak": f"Kurum Dışı-{il_adi}"
                        })

        log.info(f"[Kurum Dışı-{il_adi}] {len(ilanlar)} ilan")
    except Exception as e:
        log.warning(f"[Kurum Dışı-{il_adi}] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# Bildirim
# ──────────────────────────────────────────────────────
async def bildirim_gonder(bot, ilan):
    mesaj = (
        f"🔔 *YENİ İŞKUR İLANI*\n\n"
        f"📋 *Kaynak:* {ilan['kaynak']}\n"
        f"📌 *Detay:* {ilan['baslik']}\n"
        f"🕐 *Tespit:* {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
    )
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=mesaj,
        parse_mode=ParseMode.MARKDOWN
    )


# ──────────────────────────────────────────────────────
# Ana kontrol
# ──────────────────────────────────────────────────────
async def kontrol_et(bot, gorulmus):
    log.info("── Kontrol başlıyor ──")
    yeni = 0

    tum_ilanlar = []
    for il_adi, il_kisa, il_url in ILLER:
        tum_ilanlar += typ_cek(il_adi, il_kisa, il_url)
        tum_ilanlar += iup_cek(il_adi, il_kisa, il_url)
        tum_ilanlar += genclik_cek(il_adi, il_kisa, il_url)
        tum_ilanlar += acik_is_cek(il_adi, il_kisa, il_url)
        tum_ilanlar += kurumdisi_cek(il_adi, il_kisa, il_url)

    for ilan in tum_ilanlar:
        if not ilan.get("id"):
            continue
        anahtar = f"{ilan['kaynak']}::{ilan['id']}"
        if anahtar not in gorulmus:
            gorulmus[anahtar] = True
            gorulmus_kaydet(gorulmus)
            
            yeni += 1
            log.info(f"YENİ → {anahtar}")
            try:
                await bildirim_gonder(bot, ilan)
                await asyncio.sleep(1.5)
            except Exception as e:
                log.error(f"Bildirim hatası: {e}")

    log.info(f"Tamamlandı. Yeni: {yeni} | Toplam: {len(gorulmus)}")


async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    me = await bot.get_me()
    log.info(f"Bot bağlandı: @{me.username}")

    gorulmus = gorulmus_yukle()

    while True:
        try:
            await kontrol_et(bot, gorulmus)
        except Exception as e:
            log.error(f"Hata: {e}")
        await asyncio.sleep(KONTROL_SURESI)


if __name__ == "__main__":
    asyncio.run(main())
