"""
İŞKUR Çok İl İlan Takip Botu - Tam PostBack Fix Sürümü
Şırnak, Diyarbakır, Mardin, Siirt, Hakkari, Batman
"""

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
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
KONTROL_SURESI   = 30

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
            os.fsync(f.fileno())
    except Exception as e:
        log.error(f"Kayıt dosyasına yazılırken hata: {e}")


def tr_norm(metin):
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


def metin_gecerli_mi(metin):
    if not metin or len(metin.strip()) < 8:
        return False
    metin_lower = metin.lower()
    for gecer_metin in GECERSIZ_METINLER:
        if gecer_metin in metin_lower:
            return False
    return True


# ──────────────────────────────────────────────────────
# 1) TYP
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

        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")

        for tablo in soup2.find_all("table"):
            satirlar = tablo.find_all("tr")
            if len(satirlar) < 2:
                continue
            for satir in satirlar[1:]:
                if satir.find("th"):
                    continue
                satir_text = satir.get_text(separator=" ", strip=True)
                ilan_match = re.search(r'\b\d{6,12}\b', satir_text)
                ilan_no = ilan_match.group(0) if ilan_match else ""

                if ilan_no and metin_gecerli_mi(satir_text):
                    ilanlar.append({
                        "id": ilan_no,
                        "baslik": satir_text[:400],
                        "kaynak": f"TYP-{il_adi}"
                    })

        log.info(f"[TYP-{il_adi}] {len(ilanlar)} ilan")
    except Exception as e:
        log.warning(f"[TYP-{il_adi}] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 2) IUP
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

        for tablo in soup2.find_all("table"):
            satirlar = tablo.find_all("tr")
            if len(satirlar) < 2:
                continue
            for satir in satirlar[1:]:
                if satir.find("th"):
                    continue
                satir_text = satir.get_text(separator=" ", strip=True)
                ilan_match = re.search(r'\b\d{6,12}\b', satir_text)
                ilan_no = ilan_match.group(0) if ilan_match else ""

                if ilan_no and metin_gecerli_mi(satir_text):
                    ilanlar.append({
                        "id": ilan_no,
                        "baslik": satir_text[:400],
                        "kaynak": f"IUP-{il_adi}"
                    })
        log.info(f"[IUP-{il_adi}] {len(ilanlar)} ilan")
    except Exception as e:
        log.warning(f"[IUP-{il_adi}] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 3) Gençlik
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

        data["__EVENTTARGET"] = "ctl05$ctlCommandGenclikKayit$CommandItem_Search"
        data["__EVENTARGUMENT"] = ""

        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")
        
        for tablo in soup2.find_all("table"):
            satirlar = tablo.find_all("tr")
            if len(satirlar) < 2:
                continue
            for satir in satirlar[1:]:
                if satir.find("th"):
                    continue
                satir_text = satir.get_text(separator=" ", strip=True)
                ilan_match = re.search(r'\b\d{6,12}\b', satir_text)
                ilan_no = ilan_match.group(0) if ilan_match else ""

                if ilan_no and metin_gecerli_mi(satir_text):
                    ilanlar.append({
                        "id": ilan_no,
                        "baslik": satir_text[:400],
                        "kaynak": f"Gençlik-{il_adi}"
                    })
        log.info(f"[Gençlik-{il_adi}] {len(ilanlar)} ilan")
    except Exception as e:
        log.warning(f"[Gençlik-{il_adi}] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 4) Açık İş Kamu (Gezinme Parametresi Nokta Atışı)
# ──────────────────────────────────────────────────────
def acik_is_cek(il_adi, il_kisa, il_url):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/AcikIsIlanAra.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup:
            return ilanlar

        # 1) İl Parametresi
        il_field, il_val = il_kodu_bul(soup, il_adi)
        if il_field:
            data[il_field] = il_val

        # 2) Kamu Seçeneği (rdbIsyeriTuru)
        for rad in soup.find_all("input", {"type": "radio"}):
            rad_name = rad.get("name", "")
            if "isyeri" in rad_name.lower() or "turu" in rad_name.lower():
                data[rad_name] = "kamuRadio"

        # 3) Bitiş Tetikleyicisi (Özel Tespitten Alınan İsim)
        data["__EVENTTARGET"] = "ctl04$ctlAcikIsPageCommand_CommandItem_Search"
        data["__EVENTARGUMENT"] = ""
        data["ctl04$ctlAcikIsPageCommand_CommandItem_Search"] = "Ara"

        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")

        # HTML içindeki tüm ilan numaralarını yakala
        html_content = r.text
        ilan_nolari = set(re.findall(r'\b0*\d{7,10}\b', html_content))

        for tablo in soup2.find_all(["table", "tr", "div"]):
            txt = tablo.get_text(separator=" ", strip=True)
            for num in ilan_nolari:
                if num in txt and len(num) >= 7 and metin_gecerli_mi(txt):
                    if not any(x['id'] == num for x in ilanlar):
                        ilanlar.append({
                            "id": num,
                            "baslik": txt[:350],
                            "kaynak": f"Açık İş (Kamu)-{il_adi}"
                        })

        log.info(f"[Açık İş-{il_adi}] {len(ilanlar)} ilan")
    except Exception as e:
        log.warning(f"[Açık İş-{il_adi}] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 5) Kurum Dışı Kamu
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
            for satir in satirlar[1:]:
                if satir.find("th"):
                    continue
                hucreler = satir.find_all("td")
                if len(hucreler) >= 2:
                    link = satir.find("a", href=True)
                    ilan_id = ""
                    if link:
                        href = link["href"].strip()
                        ilan_id = href.split("/")[-1].split("?")[0]

                    metin = " | ".join(h.get_text(strip=True) for h in hucreler if h.get_text(strip=True))

                    if ilan_id and metin_gecerli_mi(metin):
                        ilanlar.append({
                            "id": ilan_id,
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
