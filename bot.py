"""
İŞKUR Şırnak İlan Takip Botu
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
KONTROL_SURESI   = 30
KAYIT_DOSYASI    = "gorulmus_ilanlar.json"
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


def il_kodu_bul(soup, il_adi="ŞIRNAK"):
    """Dropdown'dan il kodunu bulur."""
    for sel in soup.find_all("select"):
        sel_id = sel.get("id", "") + sel.get("name", "")
        if "il" in sel_id.lower() and "ilce" not in sel_id.lower():
            for opt in sel.find_all("option"):
                if il_adi in opt.text.upper():
                    return sel.get("name") or sel.get("id"), opt.get("value", "")
    return None, None


def grid_satirlari_oku(soup, kaynak):
    """Sadece sonuç GridView tablosundan satır okur."""
    ilanlar = []
    # GridView ID'si genellikle "Grid" içerir
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
                    "kaynak": kaynak
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
def typ_cek():
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Typ/TypArama.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup:
            return ilanlar

        il_field, il_val = il_kodu_bul(soup)
        if il_field:
            data[il_field] = il_val

        btn = ara_buton_adi(soup)
        if btn:
            data[btn] = "Ara"

        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")
        ilanlar = grid_satirlari_oku(soup2, "TYP")
        log.info(f"[TYP] {len(ilanlar)} ilan bulundu")
    except Exception as e:
        log.warning(f"[TYP] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 2) IUP
# ──────────────────────────────────────────────────────
def iup_cek():
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/IstIupArama.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup:
            return ilanlar

        il_field, il_val = il_kodu_bul(soup)
        if il_field:
            data[il_field] = il_val

        btn = ara_buton_adi(soup)
        if btn:
            data[btn] = "Ara"

        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")
        ilanlar = grid_satirlari_oku(soup2, "IUP")
        log.info(f"[IUP] {len(ilanlar)} ilan bulundu")
    except Exception as e:
        log.warning(f"[IUP] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 3) Gençlik Programı
# ──────────────────────────────────────────────────────
def genclik_cek():
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/IstIskurGenclikProgramArama.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup:
            return ilanlar

        il_field, il_val = il_kodu_bul(soup)
        if il_field:
            data[il_field] = il_val

        btn = ara_buton_adi(soup)
        if btn:
            data[btn] = "Ara"

        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")
        ilanlar = grid_satirlari_oku(soup2, "Gençlik Programı")
        log.info(f"[Gençlik] {len(ilanlar)} ilan bulundu")
    except Exception as e:
        log.warning(f"[Gençlik] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 4) Açık İş (Kamu + Şırnak)
# ──────────────────────────────────────────────────────
def acik_is_cek():
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/AcikIsIlanAra.aspx"
    try:
        session = session_ac()
        data, soup, cookies = viewstate_al(session, url)
        if not soup:
            return ilanlar

        # Kamu radio button — value genellikle "2" veya "K"
        for inp in soup.find_all("input", {"type": "radio"}):
            label = inp.find_next("label")
            label_text = label.get_text(strip=True) if label else ""
            if "Kamu" in label_text or "KAMU" in label_text:
                data[inp.get("name")] = inp.get("value", "")
                break

        il_field, il_val = il_kodu_bul(soup)
        if il_field:
            data[il_field] = il_val

        btn = ara_buton_adi(soup)
        if btn:
            data[btn] = "Ara"

        r = session.post(url, data=data, timeout=15, cookies=cookies)
        soup2 = BeautifulSoup(r.text, "html.parser")
        ilanlar = grid_satirlari_oku(soup2, "Açık İş (Kamu)")
        log.info(f"[Açık İş] {len(ilanlar)} ilan bulundu")
    except Exception as e:
        log.warning(f"[Açık İş] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 5) Kurum Dışı Kamu
# ──────────────────────────────────────────────────────
def kurumdisi_cek():
    ilanlar = []
    url = ("https://www.iskur.gov.tr/ilanlar/kurumdisi-kamu-isci-alim-ilanlari/"
           "?idId=sirnak&il=%C5%9E%C4%B1rnak")
    try:
        session = session_ac()
        r = session.get(url, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        # Tablo ara
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
                                "kaynak": "Kurum Dışı Kamu"
                            })
                break

        # Tablo yoksa article/li dene
        if not ilanlar:
            for css in ["article", ".list-item", ".ilan-item"]:
                for el in soup.select(css):
                    metin = el.get_text(strip=True)
                    if metin and len(metin) > 20:
                        ilanlar.append({
                            "id": kisa_hash(metin),
                            "baslik": metin[:400],
                            "kaynak": "Kurum Dışı Kamu"
                        })

        log.info(f"[Kurum Dışı] {len(ilanlar)} ilan bulundu")
    except Exception as e:
        log.warning(f"[Kurum Dışı] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# Bildirim
# ──────────────────────────────────────────────────────
async def bildirim_gonder(bot, ilan):
    mesaj = (
        f"🔔 *YENİ İŞKUR İLANI — ŞIRNAK*\n\n"
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
# Ana döngü
# ──────────────────────────────────────────────────────
async def kontrol_et(bot, gorulmus):
    log.info("── Kontrol başlıyor ──")
    yeni = 0

    tum_ilanlar = []
    tum_ilanlar += typ_cek()
    tum_ilanlar += iup_cek()
    tum_ilanlar += genclik_cek()
    tum_ilanlar += acik_is_cek()
    tum_ilanlar += kurumdisi_cek()

    for ilan in tum_ilanlar:
        if not ilan.get("id"):
            continue
        anahtar = f"{ilan['kaynak']}::{ilan['id']}"
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
    log.info(f"Tamamlandı. Yeni: {yeni} | Toplam: {len(gorulmus)}")


async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    me = await bot.get_me()
    log.info(f"Bot bağlandı: @{me.username}")

    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=(
            "✅ *İŞKUR Şırnak Takip Botu Başladı*\n\n"
            "Her 30 saniyede bir kontrol ediyorum:\n"
            "• TYP (Toplum Yararına Program)\n"
            "• İUP (İşgücü Uyum Programı)\n"
            "• İŞKUR Gençlik Programı\n"
            "• Açık İş İlanları (Kamu)\n"
            "• Kurum Dışı Kamu İşçi Alım İlanları"
        ),
        parse_mode=ParseMode.MARKDOWN
    )

    gorulmus = gorulmus_yukle()

    while True:
        try:
            await kontrol_et(bot, gorulmus)
        except Exception as e:
            log.error(f"Beklenmeyen hata: {e}")
        await asyncio.sleep(KONTROL_SURESI)


if __name__ == "__main__":
    asyncio.run(main())
