"""
İŞKUR Şırnak + İzmir İlan Takip Botu
requests + BeautifulSoup — Chrome gerektirmez
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
KAYIT_DOSYASI    = "gorulmus_ilanlar.json"
HEDEF_ILLER      = ["ŞIRNAK", "İZMİR"]
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
        with open(KAYIT_DOSYASI, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def gorulmus_kaydet(veri):
    with open(KAYIT_DOSYASI, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)


def kisa_hash(metin):
    return hashlib.md5(metin.encode()).hexdigest()[:10]


def session_ac():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def viewstate_al(session, url):
    """ASP.NET hidden field'larını çeker."""
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
    """Dropdown'dan il kodunu bulur."""
    for sel in soup.find_all("select"):
        sel_id = sel.get("id", "") + sel.get("name", "")
        if "il" in sel_id.lower() and "ilce" not in sel_id.lower():
            for opt in sel.find_all("option"):
                if il_adi in opt.text.upper():
                    return sel.get("name") or sel.get("id"), opt.get("value", "")
    return None, None


def grid_satirlari_oku(soup, kaynak, il_adi):
    """Sadece sonuç GridView tablosundan satır okur."""
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
                ilanlar.append({
                    "id": hucreler[0].get_text(strip=True) or kisa_hash(metin),
                    "baslik": metin[:400],
                    "kaynak": kaynak,
                    "il": il_adi
                })
    return ilanlar


def ara_buton_adi(soup):
    """Ara butonunun name değerini bulur."""
    for inp in soup.find_all("input", {"type": ["submit", "button", "image"]}):
        val = inp.get("value", "")
        name = inp.get("name", "")
        if "Ara" in val or "Search" in name or "Ara" in name:
            return name
    return None


# ──────────────────────────────────────────────────────
# 1) TYP
# ──────────────────────────────────────────────────────
def typ_cek(il_adi):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Typ/TypArama.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup:
            return ilanlar

        for sel in soup.find_all("select"):
            opts = [o.text.strip().upper() for o in sel.find_all("option")]
            if il_adi in opts:
                for opt in sel.find_all("option"):
                    if il_adi in opt.text.strip().upper():
                        field_name = sel.get("name") or sel.get("id")
                        if field_name:
                            data[field_name] = opt.get("value", "")
                        break

        data["__EVENTTARGET"] = "ctl05$ctlCommandTypKayit$CommandItem_Search"
        data["__EVENTARGUMENT"] = ""

        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")
        ilanlar = grid_satirlari_oku(soup2, "TYP", il_adi)
        log.info(f"[TYP - {il_adi}] {len(ilanlar)} ilan bulundu")
    except Exception as e:
        log.warning(f"[TYP - {il_adi}] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 2) IUP
# ──────────────────────────────────────────────────────
def iup_cek(il_adi):
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/IstIupArama.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup:
            return ilanlar

        for sel in soup.find_all("select"):
            opts = [o.text.strip().upper() for o in sel.find_all("option")]
            if il_adi in opts:
                for opt in sel.find_all("option"):
                    if il_adi in opt.text.strip().upper():
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
        
        GECERSIZ = {"ara", "temizle", "ara | temizle", "search", "reset", ""}
        for tablo in soup2.find_all("table"):
            satirlar = tablo.find_all("tr")
            if len(satirlar) < 2:
                continue
            for satir in satirlar[1:]:
                hucreler = satir.find_all("td")
                if len(hucreler) < 1:
                    continue
                ilan_no = hucreler[0].get_text(strip=True)
                if ilan_no.lower() in GECERSIZ:
                    continue
                metin = " | ".join(h.get_text(strip=True) for h in hucreler if h.get_text(strip=True))
                if metin and len(metin) > 3 and metin.lower() not in GECERSIZ:
                    ilanlar.append({
                        "id": ilan_no or metin[:40],
                        "baslik": metin[:400],
                        "kaynak": "IUP",
                        "il": il_adi
                    })
        log.info(f"[IUP - {il_adi}] {len(ilanlar)} ilan bulundu")
    except Exception as e:
        log.warning(f"[IUP - {il_adi}] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 3) Gençlik Programı
# ──────────────────────────────────────────────────────
def genclik_cek(il_adi):
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
        ilanlar = grid_satirlari_oku(soup2, "Gençlik Programı", il_adi)
        log.info(f"[Gençlik - {il_adi}] {len(ilanlar)} ilan bulundu")
    except Exception as e:
        log.warning(f"[Gençlik - {il_adi}] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 4) Açık İş (Kamu)
# ──────────────────────────────────────────────────────
def acik_is_cek(il_adi):
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
        ilanlar = grid_satirlari_oku(soup2, "Açık İş (Kamu)", il_adi)
        log.info(f"[Açık İş - {il_adi}] {len(ilanlar)} ilan bulundu")
    except Exception as e:
        log.warning(f"[Açık İş - {il_adi}] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 5) Kurum Dışı Kamu
# ──────────────────────────────────────────────────────
def kurumdisi_cek(il_adi):
    ilanlar = []
    il_param = "izmir" if il_adi == "İZMİR" else "sirnak"
    il_str = "İzmir" if il_adi == "İZMİR" else "Şırnak"
    
    url = f"https://www.iskur.gov.tr/ilanlar/kurumdisi-kamu-isci-alim-ilanlari/?idId={il_param}&il={il_str}"
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
                            ilanlar.append({
                                "id": hucreler[0].get_text(strip=True) or kisa_hash(metin),
                                "baslik": metin[:400],
                                "kaynak": "Kurum Dışı Kamu",
                                "il": il_adi
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
                            "kaynak": "Kurum Dışı Kamu",
                            "il": il_adi
                        })

        log.info(f"[Kurum Dışı - {il_adi}] {len(ilanlar)} ilan bulundu")
    except Exception as e:
        log.warning(f"[Kurum Dışı - {il_adi}] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# Bildirim
# ──────────────────────────────────────────────────────
async def bildirim_gonder(bot, ilan):
    mesaj = (
        f"🔔 *YENİ İŞKUR İLANI — {ilan['il']}*\n\n"
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
# Ana Çalışma Mantığı
# ──────────────────────────────────────────────────────
async def kontrol_et(bot, gorulmus):
    log.info("── Kontrol başlıyor ──")
    yeni = 0

    tum_ilanlar = []
    for il in HEDEF_ILLER:
        tum_ilanlar += typ_cek(il)
        tum_ilanlar += iup_cek(il)
        tum_ilanlar += genclik_cek(il)
        tum_ilanlar += acik_is_cek(il)
        tum_ilanlar += kurumdisi_cek(il)

    for ilan in tum_ilanlar:
        if not ilan.get("id"):
            continue
        anahtar = f"{ilan['il']}::{ilan['kaynak']}::{ilan['id']}"
        if anahtar not in gorulmus:
            gorulmus[anahtar] = True
            yeni += 1
            log.info(f"YENİ → {anahtar}")
            try:
                await bildirim_gonder(bot, ilan)
                await asyncio.sleep(1)
            except Exception as e:
                log.error(f"Bildirim hatası: {e}")

    gorulmus_kaydet(gorulmus)
    log.info(f"Tamamlandı. Yeni: {yeni} | Toplam Kayıtlı: {len(gorulmus)}")


async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    me = await bot.get_me()
    log.info(f"Bot bağlandı: @{me.username}")

    gorulmus = gorulmus_yukle()
    await kontrol_et(bot, gorulmus)


if __name__ == "__main__":
    asyncio.run(main())
